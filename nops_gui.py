"""
nops_gui.py - Standalone GUI wrapper around nops.exe for PlayStation 1 dev.
"""

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".nops_gui_config.json")


def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller bundle"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


class NopsGui:
    def __init__(self, root):
        self.root = root
        self.root.title("nops.exe launcher")
        self.root.geometry("720x540")
        self.root.minsize(600, 440)

        self.process = None
        self.reader_thread = None
        self.stop_flag = threading.Event()

        self.nops_path = tk.StringVar()
        self.target_exe_path = tk.StringVar()
        self.flag_m = tk.BooleanVar(value=True)
        self.flag_debug = tk.BooleanVar(value=True)
        self.extra_flags = tk.StringVar()

        self._load_config()
        self._check_bundled_nops()
        self._build_ui()

    def _check_bundled_nops(self):
        """Auto-detect bundled nops.exe or local nops.exe in current folder"""
        bundled_nops = get_resource_path("nops.exe")
        if os.path.isfile(bundled_nops):
            self.nops_path.set(bundled_nops)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        # nops.exe location (Auto-detected if bundled)
        frame_nops = ttk.LabelFrame(self.root, text="nops.exe location")
        frame_nops.pack(fill="x", **pad)

        entry_nops = ttk.Entry(
            frame_nops, textvariable=self.nops_path, state="readonly"
        )
        entry_nops.pack(side="left", fill="x", expand=True, padx=6, pady=6)

        # Allow override standard browse button only if not bundled or needed
        ttk.Button(frame_nops, text="Browse...", command=self._pick_nops).pack(
            side="left", padx=6, pady=6
        )

        # Target EXE/PSEXE to send
        frame_target = ttk.LabelFrame(
            self.root, text="PS1 Executable to send (/exe)"
        )
        frame_target.pack(fill="x", **pad)
        ttk.Entry(frame_target, textvariable=self.target_exe_path).pack(
            side="left", fill="x", expand=True, padx=6, pady=6
        )
        ttk.Button(
            frame_target, text="Browse...", command=self._pick_target
        ).pack(side="left", padx=6, pady=6)

        # Flags
        frame_flags = ttk.LabelFrame(self.root, text="Flags")
        frame_flags.pack(fill="x", **pad)
        ttk.Checkbutton(
            frame_flags,
            text="/m  (monitor serial for output)",
            variable=self.flag_m,
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(
            frame_flags,
            text="/debug  (boot PS1 into debug mode)",
            variable=self.flag_debug,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(
            frame_flags,
            text="Extra flags (e.g., COM5 or custom parameters):",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(8, 0))
        ttk.Entry(frame_flags, textvariable=self.extra_flags).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6)
        )
        frame_flags.columnconfigure(0, weight=1)
        frame_flags.columnconfigure(1, weight=1)

        # Command Preview
        self.preview_var = tk.StringVar()
        ttk.Label(
            self.root, textvariable=self.preview_var, foreground="#555"
        ).pack(fill="x", padx=12)
        for var in (
            self.nops_path,
            self.target_exe_path,
            self.flag_m,
            self.flag_debug,
            self.extra_flags,
        ):
            var.trace_add("write", lambda *args: self._update_preview())
        self._update_preview()

        # Action Buttons
        frame_buttons = ttk.Frame(self.root)
        frame_buttons.pack(fill="x", padx=8, pady=4)
        self.run_btn = ttk.Button(
            frame_buttons, text="Send / Run", command=self._run
        )
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(
            frame_buttons, text="Stop", command=self._stop, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=6)
        ttk.Button(
            frame_buttons, text="Clear output", command=self._clear_output
        ).pack(side="left", padx=6)

        # Output Console
        frame_out = ttk.LabelFrame(self.root, text="Output")
        frame_out.pack(fill="both", expand=True, padx=8, pady=6)
        self.output = tk.Text(
            frame_out,
            wrap="word",
            bg="#111",
            fg="#0f0",
            insertbackground="#0f0",
        )
        self.output.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(frame_out, command=self.output.yview)
        scroll.pack(side="right", fill="y")
        self.output.config(yscrollcommand=scroll.set)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _pick_nops(self):
        path = filedialog.askopenfilename(
            title="Locate nops.exe", filetypes=[("Executable", "*.exe")]
        )
        if path:
            self.nops_path.set(path)
            self._save_config()

    def _pick_target(self):
        # Updated to filter both .exe and .psexe files
        path = filedialog.askopenfilename(
            title="Select PS1 Executable to send",
            filetypes=[
                ("PS1 Executables (*.exe, *.psexe)", "*.exe;*.psexe"),
                ("All Files (*.*)", "*.*"),
            ],
        )
        if path:
            self.target_exe_path.set(path)
            self._save_config()

    def _build_args(self):
        args = []
        if self.target_exe_path.get():
            args += ["/exe", self.target_exe_path.get()]
        if self.flag_m.get():
            args.append("/m")
        if self.flag_debug.get():
            args.append("/debug")
        extra = self.extra_flags.get().strip()
        if extra:
            args += extra.split()
        return args

    def _update_preview(self):
        nops = self.nops_path.get() or "nops.exe"
        args = self._build_args()
        self.preview_var.set("Command: " + " ".join([f'"{nops}"'] + args))

    def _clear_output(self):
        self.output.delete("1.0", "end")

    def _append_output(self, text):
        self.output.insert("end", text)
        self.output.see("end")

    # ---------- Process Handling ----------
    def _run(self):
        if self.process is not None:
            messagebox.showinfo(
                "Already running", "nops.exe is running. Stop it first."
            )
            return

        nops = self.nops_path.get()
        if not nops or not os.path.isfile(nops):
            messagebox.showerror(
                "Missing nops.exe", "nops.exe could not be found."
            )
            return

        if not self.target_exe_path.get():
            if not messagebox.askyesno(
                "No File Selected", "No /exe target selected. Continue?"
            ):
                return

        self._save_config()
        args = self._build_args()
        cmd = [nops] + args
        self._append_output(f"\n$ {' '.join(cmd)}\n")

        self.stop_flag.clear()
        try:
            # Set working directory to where nops.exe and DLLs reside
            nops_dir = os.path.dirname(nops) or None
            self.process = subprocess.Popen(
                cmd,
                cwd=nops_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
        except Exception as e:
            messagebox.showerror("Failed to start", str(e))
            self.process = None
            return

        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        self.reader_thread = threading.Thread(
            target=self._read_output, daemon=True
        )
        self.reader_thread.start()

    def _read_output(self):
        try:
            for line in self.process.stdout:
                if self.stop_flag.is_set():
                    break
                self.root.after(0, self._append_output, line)
        except Exception as e:
            self.root.after(0, self._append_output, f"\n[reader error: {e}]\n")
        finally:
            self.root.after(0, self._on_process_end)

    def _on_process_end(self):
        if self.process is not None:
            rc = self.process.poll()
            self._append_output(f"\n[process ended, exit code: {rc}]\n")
        self.process = None
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _stop(self):
        self.stop_flag.set()
        if self.process is not None:
            try:
                self.process.terminate()
            except Exception:
                pass

    def _on_close(self):
        self._stop()
        self._save_config()
        self.root.destroy()

    # ---------- Config Persistence ----------
    def _save_config(self):
        data = {
            "target_exe_path": self.target_exe_path.get(),
            "flag_m": self.flag_m.get(),
            "flag_debug": self.flag_debug.get(),
            "extra_flags": self.extra_flags.get(),
        }
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _load_config(self):
        if not os.path.isfile(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            self.target_exe_path.set(data.get("target_exe_path", ""))
            self.flag_m.set(data.get("flag_m", True))
            self.flag_debug.set(data.get("flag_debug", True))
            self.extra_flags.set(data.get("extra_flags", ""))
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use("vista")
    except Exception:
        pass
    app = NopsGui(root)
    root.mainloop()