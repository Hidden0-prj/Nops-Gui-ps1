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

# Import windnd for drag-and-drop support on Windows
try:
    import windnd
except ImportError:
    windnd = None

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".nops_gui_config.json")


def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller bundle"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


class NopsGui:
    def __init__(self, root):
        self.root = root
        self.root.title("Nops Gui Launcher")
        self.root.geometry("720x560")
        self.root.minsize(680, 460)

        # Capture the system's default background color for toggling back to light mode
        self.default_bg = self.root.cget("bg")

        self.process = None
        self.reader_thread = None
        self.stop_flag = threading.Event()
        self._fast_warned = False  # Track if we already showed the /fast warning

        # Hardcode the internal path to the bundled nops.exe
        self.nops_exe = get_resource_path("nops.exe")

        self.target_exe_path = tk.StringVar()
        self.flag_m = tk.BooleanVar(value=True)
        self.flag_debug = tk.BooleanVar(value=False)
        self.extra_flags = tk.StringVar()
        
        self.com_port = tk.StringVar(value="")
        self.speed_mode = tk.StringVar(value="Normal")
        
        self.is_dark_mode = tk.BooleanVar(value=False)

        self._load_config()
        self._build_ui()
        self._check_startup_args()
        
        # Apply theme immediately on startup
        self._apply_theme()

        if windnd:
            windnd.hook_dropfiles(self.root, func=self._on_drop)
            
        if not os.path.isfile(self.nops_exe):
            self.root.after(500, lambda: self._append_output(">>> [WARNING] nops.exe not found in bundle directory!\n"))

    def _check_startup_args(self):
        if len(sys.argv) > 1:
            dropped_file = sys.argv[1]
            if dropped_file.lower().endswith(('.exe', '.psexe')):
                self.target_exe_path.set(dropped_file)

    def _on_drop(self, files):
        if files:
            try:
                path = files[0].decode('mbcs')
            except Exception:
                path = files[0].decode('utf-8', errors='ignore')
                
            if path.lower().endswith(('.exe', '.psexe')):
                self.target_exe_path.set(path)
                self._save_config()

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        # Target EXE/PSEXE to send
        frame_target = ttk.LabelFrame(
            self.root, text="PS1 Executable to send (/exe) - [You can Drag & Drop here]"
        )
        frame_target.pack(fill="x", **pad)
        ttk.Entry(frame_target, textvariable=self.target_exe_path).pack(
            side="left", fill="x", expand=True, padx=6, pady=6
        )
        ttk.Button(
            frame_target, text="Browse...", command=self._pick_target
        ).pack(side="left", padx=6, pady=6)

        # Flags & Settings
        frame_flags = ttk.LabelFrame(self.root, text="Settings & Flags")
        frame_flags.pack(fill="x", **pad)
        
        # Row 0
        ttk.Checkbutton(
            frame_flags,
            text="/m  (monitor serial)",
            variable=self.flag_m,
            command=self._on_m_toggle
        ).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        
        ttk.Checkbutton(
            frame_flags,
            text="/debug  (debug mode)",
            variable=self.flag_debug,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame_flags, text="Speed Mode:").grid(row=0, column=2, sticky="e", padx=6, pady=4)
        self.speed_combo = ttk.Combobox(
            frame_flags, textvariable=self.speed_mode, 
            values=["Normal", "/fast", "/slow"], state="readonly", width=12
        )
        self.speed_combo.grid(row=0, column=3, sticky="w", padx=6, pady=4)

        # Row 1
        ttk.Label(frame_flags, text="Manual COM Port:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        self.com_combo = ttk.Combobox(
            frame_flags, textvariable=self.com_port,
            values=[f"COM{i}" for i in range(1, 30)], width=12
        )
        self.com_combo.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame_flags, text="Extra flags:").grid(row=1, column=2, sticky="e", padx=6, pady=4)
        ttk.Entry(frame_flags, textvariable=self.extra_flags).grid(
            row=1, column=3, sticky="ew", padx=6, pady=4
        )
        
        frame_flags.columnconfigure(3, weight=1)

        # Command Preview
        self.preview_var = tk.StringVar()
        self.preview_label = tk.Label(
            self.root, textvariable=self.preview_var, fg="#555", anchor="w"
        )
        self.preview_label.pack(fill="x", padx=12)
        
        for var in (
            self.target_exe_path,
            self.flag_m,
            self.flag_debug,
            self.extra_flags,
            self.com_port,
            self.speed_mode
        ):
            var.trace_add("write", lambda *args: self._update_preview())
        
        self.speed_mode.trace_add("write", self._on_speed_change)
        self._on_m_toggle()
        self._update_preview()

        # Action Buttons
        frame_buttons = ttk.Frame(self.root)
        frame_buttons.pack(fill="x", padx=8, pady=10)

        self.run_btn = tk.Button(
            frame_buttons, 
            text="▶ Send / Run", 
            command=self._run,
            font=("Segoe UI", 12, "bold"),
            bg="#2E8B57",
            fg="white",
            activebackground="#1E6B40",
            activeforeground="white",
            width=16,
            height=2,
            cursor="hand2"
        )
        self.run_btn.pack(side="left", padx=(0, 16))

        self.stop_btn = ttk.Button(
            frame_buttons, text="Stop", command=self._stop, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=6)
        
        ttk.Button(
            frame_buttons, text="Clear output", command=self._clear_output
        ).pack(side="left", padx=6)

        self.dark_mode_btn = ttk.Button(
            frame_buttons, text="🌙 Dark Mode", command=self._toggle_dark_mode
        )
        self.dark_mode_btn.pack(side="right", padx=6)

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

    # ---------- Dynamic Logic ----------
    def _on_m_toggle(self):
        """Greys out the COM port dropdown if /m is selected"""
        if self.flag_m.get():
            self.com_combo.config(state="disabled")
        else:
            self.com_combo.config(state="normal")
        self._update_preview()

    def _on_speed_change(self, *args):
        """Shows hint warning when /fast is selected for the first time"""
        if self.speed_mode.get() == "/fast" and not self._fast_warned:
            messagebox.showinfo(
                "Hint!",
                "You've specified /fast. Next time you start nops, it has no way of knowing if the ps is in fast mode or not. So remember to use /fast on every command... or not at all! You can switch back and forth in most cases with the following (If you're sick of typing it).\n\nnops /fast\nnops /slow"
            )
            self._fast_warned = True

    # ---------- Theming ----------
    def _toggle_dark_mode(self):
        self.is_dark_mode.set(not self.is_dark_mode.get())
        self._apply_theme()
        self._save_config()

    def _apply_theme(self):
        style = ttk.Style()
        if self.is_dark_mode.get():
            try:
                style.theme_use("clam")
            except Exception:
                pass
            bg_color = "#2d2d2d"
            fg_color = "#ffffff"
            input_bg = "#1e1e1e"
            
            self.root.configure(bg=bg_color)
            style.configure(".", background=bg_color, foreground=fg_color, fieldbackground=input_bg, insertcolor=fg_color)
            style.configure("TFrame", background=bg_color)
            style.configure("TLabelframe", background=bg_color, foreground=fg_color, bordercolor="#555555")
            style.configure("TLabelframe.Label", background=bg_color, foreground=fg_color)
            style.configure("TButton", background="#3d3d3d", foreground=fg_color, bordercolor=bg_color)
            style.map("TButton", background=[("active", "#4d4d4d")])
            style.configure("TCheckbutton", background=bg_color, foreground=fg_color)
            style.map("TCheckbutton", background=[("active", "#3d3d3d")], indicatorcolor=[("selected", "#4a90e2")])
            
            self.preview_label.config(fg="#999999", bg=bg_color)
            self.dark_mode_btn.config(text="☀️ Light Mode")
        else:
            self.root.configure(bg=self.default_bg)
            try:
                style.theme_use("vista") 
            except Exception:
                style.theme_use("default")
            
            style.configure(".", background=self.default_bg, foreground="black", fieldbackground="white", insertcolor="black")
            style.configure("TFrame", background=self.default_bg)
            style.configure("TLabelframe", background=self.default_bg, foreground="black")
            style.configure("TLabelframe.Label", background=self.default_bg, foreground="black")
            style.configure("TCheckbutton", background=self.default_bg, foreground="black")
            
            self.preview_label.config(fg="#555555", bg=self.default_bg)
            self.dark_mode_btn.config(text="🌙 Dark Mode")

    def _pick_target(self):
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
        
        speed = self.speed_mode.get()
        if speed in ["/fast", "/slow"]:
            args.append(speed)
            
        if self.target_exe_path.get():
            args += ["/exe", self.target_exe_path.get()]
            
        if self.flag_m.get():
            args.append("/m")
            
        if self.flag_debug.get():
            args.append("/debug")
            
        extra = self.extra_flags.get().strip()
        if extra:
            args += extra.split()
            
        # Append COM port if NOT disabled by /m
        com = self.com_port.get().strip()
        if com and not self.flag_m.get():
            args.append(com)
            
        return args

    def _update_preview(self):
        args = self._build_args()
        self.preview_var.set("Command: nops.exe " + " ".join(args))

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

        if not os.path.isfile(self.nops_exe):
            messagebox.showerror(
                "Missing nops.exe", "The internal nops.exe could not be found."
            )
            return

        if not self.target_exe_path.get() and not self.flag_m.get():
            if not messagebox.askyesno(
                "No File Selected", "No /exe target selected. Continue?"
            ):
                return

        self._save_config()
        args = self._build_args()
        cmd = [self.nops_exe] + args
        self._append_output(f"\n$ nops.exe {' '.join(args)}\n")

        self.stop_flag.clear()
        try:
            nops_dir = os.path.dirname(self.nops_exe) or None
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
            "dark_mode": self.is_dark_mode.get(),
            "com_port": self.com_port.get(),
            "speed_mode": self.speed_mode.get(),
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
            self.flag_debug.set(data.get("flag_debug", False))
            self.extra_flags.set(data.get("extra_flags", ""))
            self.is_dark_mode.set(data.get("dark_mode", False))
            self.com_port.set(data.get("com_port", ""))
            self.speed_mode.set(data.get("speed_mode", "Normal"))
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
