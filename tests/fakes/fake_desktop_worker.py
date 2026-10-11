from __future__ import annotations

from typing import Any


class FakeDesktopWorker:
    def __init__(
        self,
        *,
        interactive: bool = True,
        locked: bool = False,
        elevated: bool = False,
        target_elevated: bool = False,
    ) -> None:
        self.interactive = interactive
        self.locked = locked
        self.elevated = elevated
        self.target_elevated = target_elevated
        self.launched_processes: dict[int, dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []
        self._next_pid = 7000
        self.dummy_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAE0lEQVR4nGP8z4APMOGVZRip0gBBLAET"
            "ee26JgAAAABJRU5ErkJggg=="
        )

    async def call(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append(request)
        op = request.get("op")
        if op == "probe":
            return {
                "ok": True,
                "interactive": self.interactive,
                "session_id": 1,
                "input_desktop": "Default" if not self.locked else "Winlogon",
                "locked": self.locked,
                "elevated": self.elevated,
            }
        if op == "launch":
            if not self.interactive or self.locked:
                return {"ok": False, "error": "desktop_unavailable"}
            if self.elevated:
                return {"ok": False, "error": "runtime_elevated"}
            pid = self._next_pid
            self._next_pid += 1
            hwnd = pid * 10
            process = {
                "pid": pid,
                "create_time": 1000.0,
                "hwnd": hwnd,
                "title": f"Test Window ({request.get('exe', '')})",
            }
            self.launched_processes[pid] = process
            return {"ok": True, **process}

        target = request.get("target") or {}
        pid = int(target.get("pid", 0))
        if pid not in self.launched_processes:
            return {"ok": False, "error": "target_changed"}
        tracked = self.launched_processes[pid]
        if (
            tracked["hwnd"] != target.get("hwnd")
            or abs(tracked["create_time"] - float(target.get("create_time", 0.0))) > 0.01
        ):
            return {"ok": False, "error": "target_changed"}
        if self.target_elevated:
            return {"ok": False, "error": "target_elevated"}

        if op == "inspect":
            return {
                "ok": True,
                "tree": {
                    "automation_id": "window_main",
                    "name": tracked["title"],
                    "class": "TestClass",
                    "control_type": "Window",
                    "patterns": ["Transform"],
                    "enabled": True,
                    "children": [
                        {
                            "automation_id": "15",
                            "name": "Text Editor",
                            "class": "Edit",
                            "control_type": "Edit",
                            "patterns": ["Value", "Text"],
                            "enabled": True,
                        }
                    ],
                },
            }
        if op == "invoke":
            return {
                "ok": True,
                "control": {
                    "automation_id": "btn_save",
                    "name": "Guardar",
                    "class": "Button",
                    "control_type": "Button",
                    "patterns": ["Invoke"],
                    "enabled": True,
                },
            }
        if op == "set_value":
            return {
                "ok": True,
                "control": {
                    "automation_id": "txt_input",
                    "name": "Input",
                    "class": "Edit",
                    "control_type": "Edit",
                    "patterns": ["Value"],
                    "enabled": True,
                },
            }
        if op == "type_text":
            return {"ok": True, "typed_chars": len(request.get("text", ""))}
        if op == "keys":
            return {"ok": True, "chord": request.get("chord")}
        if op == "menu":
            if request.get("path") != ["Archivo", "Guardar como..."]:
                return {"ok": False, "error": "menu_not_found"}
            return {"ok": True, "menu_path": request["path"], "command_id": 4}
        if op == "capture":
            return {"ok": True, "png_base64": self.dummy_png, "width": 800, "height": 600}
        if op == "close":
            self.launched_processes.pop(pid, None)
            return {"ok": True}
        return {"ok": False, "error": "operation_not_allowed"}
