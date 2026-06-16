import functools
import inspect
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import gradio as gr
from shared.utils.plugins import WAN2GPPlugin


class PulsebarPlugin(WAN2GPPlugin):
    SETTINGS_FILENAME = "settings.json"
    STATUS_FILENAME = "status.json"

    DEFAULT_SETTINGS = {
        "enabled": True,
        "autostart_bar": False,
        "status_path": "",
    }

    def __init__(self):
        super().__init__()
        self.name = "Pulsebar"
        self.version = "0.1.1"
        self.description = "Windows floating always-on-top progress bar for Wan2GP."

        self._settings_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._settings_path = os.path.join(os.path.dirname(__file__), self.SETTINGS_FILENAME)
        self._default_status_path = os.path.join(os.path.dirname(__file__), self.STATUS_FILENAME)
        self._settings = self._load_settings()

        self._wrapped = False
        self._process_tasks_wrapped = False
        self._queue_update_wrapped = False
        self._global_queue_ref_update_wrapped = False
        self._original_generate_video = None
        self._original_generation_fn = None
        self._generation_global_name = None
        self._original_process_tasks = None
        self._original_update_queue_data = None
        self._original_update_global_queue_ref = None

        self._run_total_tasks: Optional[int] = None
        self._completed_tasks_in_run = 0
        self._last_known_queue_len = 0
        self._bar_process = None

    def setup_ui(self):
        self.request_global("generate_media")
        self.request_global("generate_video")
        self.request_global("get_gen_info")
        self.request_global("global_queue_ref")
        self.request_global("update_queue_data")
        self.request_global("update_global_queue_ref")
        self.request_global("process_tasks")
        self.add_tab(
            tab_id="pulsebar",
            label="Pulsebar",
            component_constructor=self.create_ui,
        )

    def post_ui_setup(self, components):
        self._install_process_tasks_wrapper_if_needed()
        self._install_queue_update_wrapper_if_needed()
        self._install_global_queue_ref_wrapper_if_needed()
        self._install_generation_wrapper_if_needed()
        self._write_status(
            state="idle",
            percent=0,
            stage="idle",
            message="Wan2GP idle",
        )
        if bool(self._settings.get("autostart_bar", False)):
            self._launch_bar()
        return {}

    def create_ui(self):
        settings = self._get_settings_snapshot()
        status_path = self._resolve_status_path(settings)

        with gr.Blocks() as demo:
            gr.Markdown("## Pulsebar")
            gr.Markdown("Floating Windows progress bar for Wan2GP generations.")

            enabled = gr.Checkbox(
                label="Enable status writer",
                value=bool(settings.get("enabled", True)),
            )
            autostart = gr.Checkbox(
                label="Launch floating bar when Wan2GP starts",
                value=bool(settings.get("autostart_bar", False)),
            )
            status_path_box = gr.Textbox(
                label="Status file path",
                value=status_path,
                interactive=False,
            )
            status_preview = gr.Textbox(
                label="Current status",
                value=self._format_status_preview(),
                lines=12,
                interactive=False,
            )
            output = gr.Markdown(value=self._build_status_text(settings))

            with gr.Row():
                save_btn = gr.Button("Save", variant="primary")
                launch_btn = gr.Button("Launch floating bar")
                refresh_btn = gr.Button("Refresh status")
                reset_btn = gr.Button("Reset status")

            def save_config(enabled_value, autostart_value):
                new_settings = self._get_settings_snapshot()
                new_settings["enabled"] = bool(enabled_value)
                new_settings["autostart_bar"] = bool(autostart_value)
                self._set_settings_snapshot(new_settings, persist=True)
                if bool(enabled_value):
                    self._write_status(
                        state="idle",
                        percent=0,
                        stage="idle",
                        message="Wan2GP idle",
                    )
                return self._build_status_text(new_settings), self._format_status_preview()

            def launch_bar():
                ok, message = self._launch_bar()
                return message, self._format_status_preview()

            def refresh_status():
                return self._format_status_preview()

            def reset_status():
                self._write_status(
                    state="idle",
                    percent=0,
                    stage="idle",
                    message="Wan2GP idle",
                )
                return self._format_status_preview()

            save_btn.click(
                fn=save_config,
                inputs=[enabled, autostart],
                outputs=[output, status_preview],
                queue=False,
            )
            launch_btn.click(fn=launch_bar, outputs=[output, status_preview], queue=False)
            refresh_btn.click(fn=refresh_status, outputs=[status_preview], queue=False)
            reset_btn.click(fn=reset_status, outputs=[status_preview], queue=False)

        return demo

    def _select_generation_function(self):
        for global_name in ("generate_media", "generate_video"):
            generation_fn = getattr(self, global_name, None)
            if callable(generation_fn):
                return global_name, generation_fn
        return None, None

    def _install_generation_wrapper_if_needed(self):
        if self._wrapped:
            return

        generation_global_name, generation_fn = self._select_generation_function()
        if not generation_global_name or not callable(generation_fn):
            print("[Pulsebar] No compatible generation function found. Expected generate_media or generate_video.")
            return

        if getattr(generation_fn, "_wan2gp_pulsebar_wrapped", False):
            self._wrapped = True
            self._generation_global_name = generation_global_name
            self._original_generation_fn = getattr(
                generation_fn, "_wan2gp_pulsebar_original", generation_fn
            )
            self._original_generate_video = self._original_generation_fn
            return

        original_fn = generation_fn
        self._generation_global_name = generation_global_name
        self._original_generation_fn = original_fn
        self._original_generate_video = original_fn

        @functools.wraps(original_fn)
        def wrapped_generation(task, send_cmd, *args, **kwargs):
            state = kwargs.get("state")
            task_id = self._extract_task_id(task)
            queue_current, queue_total, queue_remaining = self._read_queue_progress(state)
            self._write_status(
                state="running",
                task_id=task_id,
                percent=0,
                stage="starting",
                message="Generation started",
                queue_current=queue_current,
                queue_total=queue_total,
                queue_remaining=queue_remaining,
            )

            def wrapped_send_cmd(*cmd_args, **cmd_kwargs):
                cmd = cmd_args[0] if len(cmd_args) >= 1 else None
                data = cmd_args[1] if len(cmd_args) >= 2 else cmd_kwargs.get("data")
                if cmd == "progress":
                    self._handle_progress_update(task_id, state, data)
                return send_cmd(*cmd_args, **cmd_kwargs)

            try:
                result = original_fn(task, wrapped_send_cmd, *args, **kwargs)
            except Exception as exc:
                queue_current, queue_total, queue_remaining = self._read_queue_progress(state)
                self._write_status(
                    state="error",
                    task_id=task_id,
                    percent=0,
                    stage="error",
                    message=str(exc),
                    queue_current=queue_current,
                    queue_total=queue_total,
                    queue_remaining=queue_remaining,
                )
                self._mark_task_complete()
                raise

            queue_current, queue_total, queue_remaining = self._read_queue_progress(state)
            if result is True:
                self._write_status(
                    state="done",
                    task_id=task_id,
                    percent=100,
                    stage="complete",
                    message="Generation completed",
                    queue_current=queue_current,
                    queue_total=queue_total,
                    queue_remaining=queue_remaining,
                )
            else:
                self._write_status(
                    state="failed",
                    task_id=task_id,
                    percent=0,
                    stage="failed",
                    message=f"Generation returned {result!r}",
                    queue_current=queue_current,
                    queue_total=queue_total,
                    queue_remaining=queue_remaining,
                )
            self._mark_task_complete()
            return result

        wrapped_generation.__signature__ = inspect.signature(original_fn)
        wrapped_generation._wan2gp_pulsebar_wrapped = True
        wrapped_generation._wan2gp_pulsebar_original = original_fn
        wrapped_generation._wan2gp_pulsebar_global_name = generation_global_name

        self.set_global(generation_global_name, wrapped_generation)
        self._wrapped = True

    def _install_process_tasks_wrapper_if_needed(self):
        if self._process_tasks_wrapped:
            return

        process_tasks_fn = getattr(self, "process_tasks", None)
        if not callable(process_tasks_fn):
            return

        if getattr(process_tasks_fn, "_wan2gp_pulsebar_process_wrapped", False):
            self._process_tasks_wrapped = True
            self._original_process_tasks = getattr(
                process_tasks_fn,
                "_wan2gp_pulsebar_process_original",
                process_tasks_fn,
            )
            return

        original_fn = process_tasks_fn
        self._original_process_tasks = original_fn

        @functools.wraps(original_fn)
        def wrapped_process_tasks(state, *args, **kwargs):
            queue_len = self._get_queue_len_from_state(state)
            with self._status_lock:
                self._last_known_queue_len = queue_len
                self._run_total_tasks = queue_len if queue_len > 0 else None
                self._completed_tasks_in_run = 0
            if queue_len > 0:
                self._write_status(
                    state="queued",
                    percent=0,
                    stage="queued",
                    message=f"{queue_len} task(s) queued",
                    queue_current=1,
                    queue_total=queue_len,
                    queue_remaining=queue_len,
                )
            return original_fn(state, *args, **kwargs)

        wrapped_process_tasks.__signature__ = inspect.signature(original_fn)
        wrapped_process_tasks._wan2gp_pulsebar_process_wrapped = True
        wrapped_process_tasks._wan2gp_pulsebar_process_original = original_fn

        self.set_global("process_tasks", wrapped_process_tasks)
        self._process_tasks_wrapped = True

    def _install_queue_update_wrapper_if_needed(self):
        if self._queue_update_wrapped:
            return

        update_queue_data_fn = getattr(self, "update_queue_data", None)
        if not callable(update_queue_data_fn):
            return

        if getattr(update_queue_data_fn, "_wan2gp_pulsebar_queue_wrapped", False):
            self._queue_update_wrapped = True
            self._original_update_queue_data = getattr(
                update_queue_data_fn, "_wan2gp_pulsebar_queue_original", update_queue_data_fn
            )
            return

        original_fn = update_queue_data_fn
        self._original_update_queue_data = original_fn

        @functools.wraps(original_fn)
        def wrapped_update_queue_data(queue, *args, **kwargs):
            self._capture_queue_len(queue)
            return original_fn(queue, *args, **kwargs)

        wrapped_update_queue_data.__signature__ = inspect.signature(original_fn)
        wrapped_update_queue_data._wan2gp_pulsebar_queue_wrapped = True
        wrapped_update_queue_data._wan2gp_pulsebar_queue_original = original_fn

        self.set_global("update_queue_data", wrapped_update_queue_data)
        self._queue_update_wrapped = True

    def _install_global_queue_ref_wrapper_if_needed(self):
        if self._global_queue_ref_update_wrapped:
            return

        update_global_queue_ref_fn = getattr(self, "update_global_queue_ref", None)
        if not callable(update_global_queue_ref_fn):
            return

        if getattr(update_global_queue_ref_fn, "_wan2gp_pulsebar_global_queue_wrapped", False):
            self._global_queue_ref_update_wrapped = True
            self._original_update_global_queue_ref = getattr(
                update_global_queue_ref_fn,
                "_wan2gp_pulsebar_global_queue_original",
                update_global_queue_ref_fn,
            )
            return

        original_fn = update_global_queue_ref_fn
        self._original_update_global_queue_ref = original_fn

        @functools.wraps(original_fn)
        def wrapped_update_global_queue_ref(queue, *args, **kwargs):
            self._capture_queue_len(queue)
            return original_fn(queue, *args, **kwargs)

        wrapped_update_global_queue_ref.__signature__ = inspect.signature(original_fn)
        wrapped_update_global_queue_ref._wan2gp_pulsebar_global_queue_wrapped = True
        wrapped_update_global_queue_ref._wan2gp_pulsebar_global_queue_original = original_fn

        self.set_global("update_global_queue_ref", wrapped_update_global_queue_ref)
        self._global_queue_ref_update_wrapped = True

    def _handle_progress_update(self, task_id: Any, state: Any, data: Any):
        step_no, total_no = self._extract_step_total_from_progress_data(data)
        if step_no is None or total_no is None:
            return
        percent = int((float(step_no) * 100.0) / float(total_no))
        percent = max(0, min(100, percent))
        queue_current, queue_total, queue_remaining = self._read_queue_progress(state)
        self._write_status(
            state="running",
            task_id=task_id,
            percent=percent,
            stage="sampling",
            message=f"Step {step_no}/{total_no}",
            queue_current=queue_current,
            queue_total=queue_total,
            queue_remaining=queue_remaining,
        )

    def _extract_step_total_from_progress_data(self, data: Any):
        step_value = None
        total_value = None

        if isinstance(data, dict):
            step_value = data.get("step") or data.get("current") or data.get("step_no")
            total_value = data.get("total") or data.get("total_steps")
        elif isinstance(data, (list, tuple)) and len(data) > 0:
            first = data[0]
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                step_value = first[0]
                total_value = first[1]
            elif len(data) >= 3:
                step_value = first
                total_value = data[2]

        try:
            step_no = int(step_value)
            total_no = int(total_value)
        except Exception:
            return None, None

        if total_no <= 0 or step_no < 0:
            return None, None
        return step_no, total_no

    def _capture_queue_len(self, queue: Any):
        if not isinstance(queue, list):
            return
        qlen = len(queue)
        with self._status_lock:
            self._last_known_queue_len = qlen
            if self._run_total_tasks is None and qlen > 0:
                self._run_total_tasks = qlen
                self._completed_tasks_in_run = 0
            elif self._run_total_tasks is not None and qlen > self._run_total_tasks:
                self._run_total_tasks = qlen
            if qlen <= 0:
                self._run_total_tasks = None
                self._completed_tasks_in_run = 0

    def _get_queue_len_from_state(self, state: Any) -> int:
        get_gen_info_fn = getattr(self, "get_gen_info", None)
        if not callable(get_gen_info_fn):
            return 0
        try:
            gen = get_gen_info_fn(state)
            queue = gen.get("queue", []) if isinstance(gen, dict) else []
            return len(queue) if isinstance(queue, list) else 0
        except Exception:
            return 0

    def _read_queue_progress(self, state: Any):
        state_queue_len = self._get_queue_len_from_state(state)
        with self._status_lock:
            total_hints = [self._last_known_queue_len, state_queue_len]
            best_total = max([h for h in total_hints if isinstance(h, int)] + [0])
            if best_total > 0:
                if self._run_total_tasks is None or best_total > self._run_total_tasks:
                    self._run_total_tasks = best_total
                total = int(self._run_total_tasks)
                current = min(total, max(1, self._completed_tasks_in_run + 1))
                remaining = max(0, total - self._completed_tasks_in_run)
                return current, total, remaining
        return None, None, state_queue_len if state_queue_len > 0 else None

    def _mark_task_complete(self):
        with self._status_lock:
            self._completed_tasks_in_run += 1
            if self._run_total_tasks is not None and self._completed_tasks_in_run >= self._run_total_tasks:
                self._run_total_tasks = None
                self._completed_tasks_in_run = 0

    def _write_status(
        self,
        state: str,
        percent: Optional[int] = None,
        stage: Optional[str] = None,
        message: Optional[str] = None,
        task_id: Any = None,
        queue_current: Optional[int] = None,
        queue_total: Optional[int] = None,
        queue_remaining: Optional[int] = None,
    ):
        settings = self._get_settings_snapshot()
        if not bool(settings.get("enabled", True)):
            return

        payload = {
            "state": state,
            "task_id": task_id,
            "percent": int(max(0, min(100, percent if percent is not None else 0))),
            "stage": stage or state,
            "message": message or state,
            "queue": {
                "current": queue_current,
                "total": queue_total,
                "remaining": queue_remaining,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        path = self._resolve_status_path(settings)
        tmp_path = f"{path}.tmp"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._status_lock:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            os.replace(tmp_path, path)

    def _read_status_file(self):
        path = self._resolve_status_path(self._get_settings_snapshot())
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return {}

    def _format_status_preview(self):
        status = self._read_status_file()
        if not status:
            return "No status file found yet."
        return json.dumps(status, indent=2, ensure_ascii=False)

    def _launch_bar(self):
        if os.name != "nt":
            return False, "Pulsebar desktop app is Windows-only."

        status_path = self._resolve_status_path(self._get_settings_snapshot())
        desktop_dir = os.path.join(os.path.dirname(__file__), "desktop")
        publish_exe = os.path.join(desktop_dir, "publish", "Wan2GP.PulseBar.exe")
        csproj = os.path.join(desktop_dir, "Wan2GP.PulseBar.csproj")

        if self._bar_process is not None and self._bar_process.poll() is None:
            return True, "Pulsebar is already running."

        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "DETACHED_PROCESS"):
            creationflags |= subprocess.DETACHED_PROCESS

        try:
            if os.path.exists(publish_exe):
                args = [publish_exe, status_path]
            else:
                args = ["dotnet", "run", "--project", csproj, "--", status_path]
            self._bar_process = subprocess.Popen(
                args,
                cwd=desktop_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            return True, f"Launched Pulsebar using {args[0]}"
        except FileNotFoundError:
            return False, "Could not launch Pulsebar. Install .NET SDK or publish desktop/Wan2GP.PulseBar.csproj."
        except Exception as exc:
            return False, f"Could not launch Pulsebar: {exc}"

    def _resolve_status_path(self, settings: Dict[str, Any]) -> str:
        configured = str(settings.get("status_path") or "").strip()
        return configured if configured else self._default_status_path

    def _build_status_text(self, settings: Dict[str, Any]) -> str:
        enabled = "Enabled" if settings.get("enabled", True) else "Disabled"
        autostart = "Enabled" if settings.get("autostart_bar", False) else "Disabled"
        return (
            f"**Status writer:** {enabled}  \n"
            f"**Autostart:** {autostart}  \n"
            f"**Status file:** `{self._resolve_status_path(settings)}`"
        )

    def _load_settings(self):
        try:
            with open(self._settings_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except Exception:
            loaded = {}
        merged = dict(self.DEFAULT_SETTINGS)
        if isinstance(loaded, dict):
            merged.update(loaded)
        return merged

    def _set_settings_snapshot(self, settings: Dict[str, Any], persist: bool = False):
        with self._settings_lock:
            merged = dict(self.DEFAULT_SETTINGS)
            merged.update(settings)
            self._settings = merged
            if persist:
                tmp_path = f"{self._settings_path}.tmp"
                with open(tmp_path, "w", encoding="utf-8") as handle:
                    json.dump(merged, handle, indent=2)
                os.replace(tmp_path, self._settings_path)

    def _get_settings_snapshot(self):
        with self._settings_lock:
            return json.loads(json.dumps(self._settings))

    def _extract_task_id(self, task: Any):
        if isinstance(task, dict):
            return task.get("id", "unknown")
        return "unknown"
