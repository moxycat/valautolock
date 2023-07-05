import PySimpleGUI as sg
import asyncio
from threading import Thread
from utils import Valorant

def asyncloop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


val = Valorant()

loop, thr = None, None

def start():
    loop = asyncio.new_event_loop()
    t = Thread(target=asyncloop, args=(loop,))
    t.start()
    asyncio.run_coroutine_threadsafe(val.connect_websocket(), loop)
    return loop, t

def stop(loop, t):
    if loop is None or t is None: return
    loop.call_soon_threadsafe(loop.stop)
    t.join()

agents = val.get_agents()

sg.theme("Default1")
sg.set_options(font=("Consolas", 10))

agent_names = [agent["name"] for agent in agents]

layout = [
    sg.vtop([
        sg.Column([
                [
                    sg.Listbox(
                        values=agent_names,
                        size=(10, 10),
                        enable_events=True,
                        key="agent_list"
                    )
                ]
            ], pad=0
        ),
        sg.Column([
            [sg.Multiline("", size=(25, 8), disabled=True, background_color="white", auto_refresh=True, autoscroll=True, key="status")],
            [sg.Button("Enable", key="toggle")],

        ], pad=0)
    ])
]

window = sg.Window("VALORANT Autolock Tool", layout, finalize=True)
status = window["status"]

selected_agent_index = None
enabled = False

while True:
    e, v = window.read()
    print(e)
    if e == None: break
    if e == "agent_list":
        ix = window["agent_list"].get_indexes()[0]
        selected_agent_index = ix
        status.print(f"Selected {agents[ix]['name']}")
        val.select_agent(agents[ix]["name"])
    
    if e == "toggle":
        if enabled:
            status.print(f"Disabled autolocker")
            window["toggle"].update("Enable")
            window["agent_list"].update(disabled=False)
            stop(loop, thr)
            enabled = False
        else:
            if selected_agent_index is None:
                status.print("No agent selected")
            else:
                status.print("Enabled autolocker")
                window["toggle"].update("Disable")
                window["agent_list"].update(disabled=True)
                loop, thr = start()
                enabled = True

window.close()
stop(loop, thr)