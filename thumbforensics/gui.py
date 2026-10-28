"""Interface gráfica (Tkinter), no mesmo modelo do ileappGUI.py: o trabalho roda
numa thread e as mensagens chegam à janela por uma fila, para ela não travar."""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__, acquire, api, phash, plugins
from .seekers import detect

KIND_LABEL = {
    "pasta": "pasta de extração",
    "zip": "arquivo .zip",
    "tar": "arquivo .tar",
    "backup": "backup do iTunes/Finder",
}
PLATFORM_LABEL = {"ios": "iPhone (iOS)", "android": "Android", "any": "Outros"}


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — abre com o programa padrão do Windows
    else:
        webbrowser.open(path.resolve().as_uri())


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.messages: queue.Queue = queue.Queue()
        self.busy = False
        self.report: Path | None = None

        root.title(f"thumbforensics {__version__}")
        root.minsize(760, 640)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        self.acq_platform = StringVar(value="ios")
        self.acq_dest = StringVar()
        self.device_status = StringVar(value="Plugue o aparelho e clique em “Verificar conexão”.")
        self.src = StringVar()
        self.src_kind = StringVar(value="Escolha uma pasta, um .zip/.tar ou a pasta de um backup.")
        self.out = StringVar()
        self.plugin_dir = StringVar()
        self.use_phash = BooleanVar(value=phash.available())
        self.artifact_vars: dict[str, BooleanVar] = {}

        self._build_acquire()
        self._build_analyze()
        self._build_actions()
        self._build_log()
        self._load_plugins()
        self.src.trace_add("write", lambda *_: self._on_source_change())
        root.after(100, self._poll)

    # ---------- layout ----------

    def _build_acquire(self):
        f = ttk.LabelFrame(self.root, text=" 1. Copiar do celular (USB) ", padding=10)
        f.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        f.columnconfigure(1, weight=1)
        plat = ttk.Frame(f)
        plat.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(plat, text="iPhone", value="ios", variable=self.acq_platform).pack(side="left")
        ttk.Radiobutton(plat, text="Android", value="android", variable=self.acq_platform).pack(side="left", padx=12)
        ttk.Label(f, text="Salvar em:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.acq_dest).grid(row=1, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(f, text="Escolher…", command=lambda: self._pick_dir(self.acq_dest)).grid(row=1, column=2, pady=(8, 0))
        actions = ttk.Frame(f)
        actions.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.check_button = ttk.Button(actions, text="Verificar conexão", command=self._start_check)
        self.check_button.pack(side="left")
        self.acq_button = ttk.Button(actions, text="Copiar do aparelho", command=self._start_acquire)
        self.acq_button.pack(side="left", padx=(6, 0))
        ttk.Label(actions, textvariable=self.device_status, wraplength=430).pack(side="left", padx=(10, 0))
        ttk.Label(f, foreground="gray", text=(
            "iPhone: desbloqueado, com “Confiar” aceito e pymobiledevice3 instalado.\n"
            "Android: Depuração USB ativa e adb instalado.")).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _build_analyze(self):
        f = ttk.LabelFrame(self.root, text=" 2. Analisar ", padding=10)
        f.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Origem:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.src).grid(row=0, column=1, sticky="ew", padx=6)
        b = ttk.Frame(f)
        b.grid(row=0, column=2)
        ttk.Button(b, text="Pasta…", command=lambda: self._pick_dir(self.src)).pack(side="left")
        ttk.Button(b, text="Arquivo…", command=self._pick_archive).pack(side="left", padx=(4, 0))
        ttk.Label(f, textvariable=self.src_kind, foreground="gray").grid(row=1, column=1, sticky="w", padx=6)

        ttk.Label(f, text="Saída:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.out).grid(row=2, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(f, text="Escolher…", command=lambda: self._pick_dir(self.out)).grid(row=2, column=2, sticky="w", pady=(8, 0))

        ttk.Label(f, text="Plugins extras:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.plugin_dir).grid(row=3, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(f, text="Escolher…", command=self._pick_plugins).grid(row=3, column=2, sticky="w", pady=(8, 0))

        self.artifacts_frame = ttk.Frame(f)
        self.artifacts_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        opts = ttk.Frame(f)
        opts.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        cb = ttk.Checkbutton(opts, text="Comparação visual com os originais (reduz falsos positivos)",
                             variable=self.use_phash)
        cb.pack(side="left")
        if not phash.available():
            cb.state(["disabled"])
            ttk.Label(opts, text="  — requer Pillow", foreground="gray").pack(side="left")

    def _build_actions(self):
        f = ttk.Frame(self.root)
        f.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        f.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(f, text="Analisar", command=self._start_analyze)
        self.run_button.grid(row=0, column=0)
        self.progress = ttk.Progressbar(f, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=10)
        self.progress.grid_remove()  # só aparece durante o trabalho
        self.open_button = ttk.Button(f, text="Abrir relatório", command=self._open_report, state="disabled")
        self.open_button.grid(row=0, column=2)

    def _build_log(self):
        self.log_box = ScrolledText(self.root, height=12, state="disabled", wrap="word", font=("Consolas", 9))
        self.log_box.grid(row=3, column=0, sticky="nsew", padx=12, pady=(6, 12))

    # ---------- artefatos ----------

    def _load_plugins(self):
        extra = [Path(self.plugin_dir.get())] if self.plugin_dir.get() else []
        try:
            available = plugins.load(extra)
        except Exception as ex:  # plugin externo com erro
            messagebox.showerror("Plugins", f"Não foi possível carregar os plugins:\n{ex}")
            self.plugin_dir.set("")
            available = plugins.load()
        self.available = available
        previous = {k: v.get() for k, v in self.artifact_vars.items()}
        for w in self.artifacts_frame.winfo_children():
            w.destroy()
        self.artifact_vars = {}
        groups: dict[str, list] = {}
        for pl in sorted(available.values(), key=lambda p: (p.order, p.key)):
            groups.setdefault(pl.platform, []).append(pl)
        for col, platform in enumerate(sorted(groups, key=lambda x: ("ios", "android", "any").index(x)
                                              if x in ("ios", "android", "any") else 9)):
            box = ttk.LabelFrame(self.artifacts_frame, text=f" {PLATFORM_LABEL.get(platform, platform)} ", padding=6)
            box.grid(row=0, column=col, sticky="nsew", padx=(0, 8))
            self.artifacts_frame.columnconfigure(col, weight=1)
            for pl in groups[platform]:
                var = BooleanVar(value=previous.get(pl.key, True))
                self.artifact_vars[pl.key] = var
                ttk.Checkbutton(box, text=pl.name, variable=var).pack(anchor="w")

    # ---------- escolhas ----------

    def _pick_dir(self, var: StringVar):
        path = filedialog.askdirectory(parent=self.root)
        if path:
            var.set(path)

    def _pick_archive(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[
            ("Extrações", "*.zip *.tar *.tar.gz *.tgz"), ("Todos os arquivos", "*.*")])
        if path:
            self.src.set(path)

    def _pick_plugins(self):
        self._pick_dir(self.plugin_dir)
        self._load_plugins()

    def _on_source_change(self):
        src = Path(self.src.get()) if self.src.get() else None
        kind = detect(src) if src else None
        if src is None:
            self.src_kind.set("Escolha uma pasta, um .zip/.tar ou a pasta de um backup.")
        elif kind is None:
            self.src_kind.set("Formato não reconhecido.")
        else:
            self.src_kind.set(f"Detectado: {KIND_LABEL[kind]}")
            if not self.out.get():
                self.out.set(str(src.parent / f"saida-{src.stem}"))

    # ---------- execução ----------

    def log(self, text: str):
        self.messages.put(("log", text))

    def _poll(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "done":
                    self._set_busy(False)
                    if payload:
                        payload()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.run_button.configure(state=state)
        self.acq_button.configure(state=state)
        self.check_button.configure(state=state)
        if busy:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _in_background(self, work):
        self._set_busy(True)

        def target():
            after = None
            try:
                after = work()
            except Exception:
                self.log(traceback.format_exc())
                after = lambda: messagebox.showerror("Erro", "Algo deu errado. Veja os detalhes no registro.")
            self.messages.put(("done", after))

        threading.Thread(target=target, daemon=True).start()

    def _start_check(self):
        platform = self.acq_platform.get()
        self.device_status.set("Procurando…")

        def work():
            ok, message = acquire.check(platform)
            self.log(("✔ " if ok else "✘ ") + message)
            return lambda: self.device_status.set(("✔ " if ok else "✘ ") + message.splitlines()[0])

        self._in_background(work)

    def _start_acquire(self):
        if not self.acq_dest.get():
            messagebox.showwarning("Copiar do celular", "Escolha onde salvar a cópia.")
            return
        platform, dest = self.acq_platform.get(), Path(self.acq_dest.get())

        def work():
            ok, message = acquire.check(platform)
            self.log(("✔ " if ok else "✘ ") + message)
            if not ok:
                return lambda: (self.device_status.set("✘ " + message.splitlines()[0]),
                                messagebox.showwarning("Copiar do celular", message))
            self.log(f"--- Copiando do {'iPhone' if platform == 'ios' else 'Android'} para {dest}")
            code = acquire.run(platform, dest, log=self.log)
            log_file = dest / acquire.LOG_NAME
            if code == acquire.OK:
                self.log(f"Cópia concluída. Registro salvo em {log_file}.")
                return lambda: self.src.set(str(dest))
            if code == acquire.PARTIAL:
                self.log(f"Cópia PARCIAL: alguma pasta falhou. Registro salvo em {log_file}.")
                return lambda: (self.src.set(str(dest)), messagebox.showwarning(
                    "Copiar do celular", "A cópia foi parcial: alguma pasta falhou.\n"
                    f"A análise pode ficar incompleta. Veja o registro em:\n{log_file}"))
            return lambda: messagebox.showwarning("Copiar do celular", "A cópia falhou. Veja o registro.")

        self._in_background(work)

    def _start_analyze(self):
        if not self.src.get() or not self.out.get():
            messagebox.showwarning("Analisar", "Escolha a origem e a pasta de saída.")
            return
        keys = [k for k, v in self.artifact_vars.items() if v.get()]
        src, out, use_phash = Path(self.src.get()), Path(self.out.get()), self.use_phash.get()
        chosen = api.select(self.available, keys)
        self.open_button.configure(state="disabled")

        def work():
            self.log(f"--- Analisando {src}")
            try:
                api.analyze(src, out, chosen, use_phash, log=self.log)
            except api.AnalysisError as ex:
                self.log(str(ex))
                return lambda: messagebox.showwarning("Analisar", str(ex))
            report = out / "relatorio.html"

            def finished():
                self.report = report
                self.open_button.configure(state="normal")
                if messagebox.askyesno("Análise concluída", "Abrir o relatório agora?"):
                    self._open_report()
            return finished

        self._in_background(work)

    def _open_report(self):
        if self.report and self.report.exists():
            open_path(self.report)


def main() -> int:
    root = Tk()
    try:
        ttk.Style(root).theme_use("vista" if sys.platform == "win32" else "clam")
    except Exception:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
