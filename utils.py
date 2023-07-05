import requests
import os
from base64 import b64encode, b64decode
import ssl
import websockets as ws
import json
import traceback
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) # annoying

# for some reason using an enum didn't work as expected
# and i don't know why so this rather strange alternative is used
IN_MENU = 1
IN_QUEUE = 2
MATCH_FOUND = 3
AGENT_SELECT = 4
IN_GAME = 5
UNKNOWN = 6

class Valorant:
    def __init__(self):
        self.read_lockfile()
        self.get_token_and_entitlement()
        self.get_puuid()
        self.get_region()
        self.get_presence()
        self.locked = False
    
    def get_agents(self):
        resp = requests.get("https://valorant-api.com/v1/agents?isPlayableCharacter=true")
        resp.raise_for_status()
        data = resp.json()
        agents = []
        for agent in data["data"]:
            agents.append({
                "uuid": agent["uuid"],
                "name": agent["displayName"],
                "icon": agent["displayIcon"]
            })
        agents.sort(key=lambda d: d["name"])
        self.agents = agents
        return agents

    def select_agent(self, name):
        for agent in self.agents:
            if agent["name"] == name:
                self.selected_agent = agent["uuid"]
                return
        self.selected_agent = None

    def read_lockfile(self):
        lockfile_path = os.path.join(os.getenv("LOCALAPPDATA"), r"Riot Games\Riot Client\Config\lockfile")
        with open(lockfile_path, "r") as f:
            data = f.read().split(":")
        name, pid, port, password, protocol = data
        lockfile = {
            "name": name,
            "pid": pid,
            "port": port,
            "password": password,
            "protocol": protocol
        }
        self.lockfile = lockfile

    def get_token_and_entitlement(self):
        url = f"{self.lockfile['protocol']}://127.0.0.1:{self.lockfile['port']}/entitlements/v1/token"
        resp = requests.get(url, headers={
            "Authorization": "Basic %s" % b64encode(f"riot:{self.lockfile['password']}".encode()).decode()
        }, verify=ssl.CERT_NONE)
        resp.raise_for_status()
        data = resp.json()
        self.token = data["accessToken"]
        self.entitlement = data["token"]
        return (self.token, self.entitlement)

    def get_puuid(self):
        resp = requests.get("https://auth.riotgames.com/userinfo", headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        })
        resp.raise_for_status()
        data = resp.json()
        self.puuid = data["sub"]
        return self.puuid
    
    def get_region(self):
        path = os.path.join(os.getenv("LOCALAPPDATA"), r"VALORANT\Saved\Logs\ShooterGame.log")
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.count("https://glz") > 0:
                    x = line.split("https://glz-")[1].split(".")
                    if x[1] == "pbe":
                        self.region = "na-1"
                        self.shard = "na"
                    else:
                        self.region = x[0]
                        self.shard = x[1]
                    return (self.region, self.shard)

    def get_pregame_match_id(self):
        resp = requests.get(f"https://glz-{self.region}.{self.shard}.a.pvp.net/pregame/v1/players/{self.puuid}", headers={
            "X-Riot-Entitlements-JWT": self.entitlement,
            "Authorization": f"Bearer {self.token}"
        }, verify=ssl.CERT_NONE)
        resp.raise_for_status()
        data = resp.json()
        print(data)
        self.match_id = data["MatchID"]
        return self.match_id

    def _calc_state(self, state, party_state):
        # state     party_state                meaning
        # -------------------------------------------------
        # MENUS   + DEFAULT                 => not in queue
        # MENUS   + MATCHMAKING             => in queue
        # PREGAME + MATCHMADE_GAME_STARTING => match found
        # PREGAME + DEFAULT                 => agent select
        # INGAME  + DEFAULT                 => in game
        print(state, party_state)
        if state == "MENUS" and party_state == "DEFAULT": return IN_MENU
        elif state == "MENUS" and party_state == "MATCHMAKING": return IN_QUEUE
        elif state == "PREGAME" and party_state == "MATCHMADE_GAME_STARTING": return MATCH_FOUND
        elif state == "PREGAME" and party_state == "DEFAULT": return AGENT_SELECT
        elif state == "INGAME" and party_state == "DEFAULT": return IN_GAME
        else: return UNKNOWN

    def get_presence(self):
        url = f"{self.lockfile['protocol']}://127.0.0.1:{self.lockfile['port']}/chat/v4/presences"
        resp = requests.get(url, headers={
            "Authorization": "Basic %s" % b64encode(f"riot:{self.lockfile['password']}".encode()).decode()
        }, verify=ssl.CERT_NONE)
        resp.raise_for_status()
        data = resp.json()
        presences = data["presences"]
        for presence in presences:
            if presence["puuid"] == self.puuid:
                private = json.loads(b64decode(presence["private"]).decode())
                state = private["sessionLoopState"]
                party_state = private["partyState"]
                self.state = self._calc_state(state, party_state)
                return self.state
    
    def lock_agent(self, agent_uuid):
        resp = requests.post(f"https://glz-{self.region}.{self.shard}.a.pvp.net/pregame/v1/matches/{self.match_id}/lock/{agent_uuid}", headers={
            "X-Riot-Entitlements-JWT": self.entitlement,
            "Authorization": f"Bearer {self.token}"
        }, verify=ssl.CERT_NONE)
        resp.raise_for_status()
        print(resp.text)
        # FINISH THIS !!!!
    
    async def connect_websocket(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sock = ws.connect(f"wss://127.0.0.1:{self.lockfile['port']}", extra_headers={
            "Authorization": "Basic %s" % b64encode(f"riot:{self.lockfile['password']}".encode()).decode()
        }, ssl=ctx)
        async with sock as s:
            await s.send("[5, \"OnJsonApiEvent_chat_v4_presences\"]")
            while True:
                resp = await s.recv()
                self.handle_response(resp)

    def handle_response(self, message):
        if len(message) <= 10: return None
        data = json.loads(message)
        presences = data[2]["data"]["presences"][0]
        if presences["puuid"] != self.puuid: return None
        if presences["product"] != "valorant": return None
        private = json.loads(b64decode(presences["private"]).decode())
    
        state = private["sessionLoopState"] # MENUS, PREGAME, INGAME
        party_state = private["partyState"] # DEFAULT, MATCHMAKING, MATCHMADE_GAME_STARTING

    
        #print(state, party_state)
        self.state = self._calc_state(state, party_state)
        print(self.state)

        if self.state in [IN_MENU, IN_QUEUE, IN_GAME, MATCH_FOUND]: self.locked = False
        elif self.state == AGENT_SELECT and not self.locked:
            print("in agent select")
            self.get_pregame_match_id()
            print("Match ID:", self.match_id)
            try: self.lock_agent(self.selected_agent)
            except: traceback.print_exc()
            else: self.locked = True