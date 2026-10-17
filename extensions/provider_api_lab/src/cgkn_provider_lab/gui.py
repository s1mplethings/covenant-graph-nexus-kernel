from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Any, Callable

from .models import ComparisonOptions, ConfigurationError, ProviderConfig, ProviderResult
from .presets import PRESETS, PRESETS_BY_NAME
from .redaction import redact_text
from .secrets import SecretError
from .service import ProviderComparisonService
from .storage import ProviderConfigStore


class ProviderLabApp(tk.Tk):
    def __init__(
        self,
        store: ProviderConfigStore | None = None,
        service: ProviderComparisonService | None = None,
    ) -> None:
        super().__init__()
        self.title("CGKN Provider API Lab")
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.store = store or ProviderConfigStore()
        self.service = service or ProviderComparisonService()
        self.providers: list[ProviderConfig] = []
        self.latest_results: list[ProviderResult] = []
        self.latest_selected: list[ProviderConfig] = []
        self.latest_options = ComparisonOptions()
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._busy = False
        self._build_ui()
        self._load_providers()
        self.after(100, self._poll_events)

    def _build_ui(self) -> None:
        banner = ttk.Frame(self, padding=(12, 10))
        banner.pack(fill=tk.X)
        ttk.Label(
            banner,
            text="密钥只进入系统凭据库、环境变量或本次运行内存；不会写入仓库、配置导出或错误日志。",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor=tk.W)
        self.path_label = ttk.Label(banner, text=f"配置位置：{self.store.path}")
        self.path_label.pack(anchor=tk.W, pady=(4, 0))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.provider_tab = ttk.Frame(self.notebook, padding=10)
        self.compare_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.provider_tab, text="供应商")
        self.notebook.add(self.compare_tab, text="对比测试")
        self._build_provider_tab()
        self._build_compare_tab()

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(
            fill=tk.X, side=tk.BOTTOM
        )

    def _build_provider_tab(self) -> None:
        self.provider_tab.columnconfigure(0, weight=3)
        self.provider_tab.columnconfigure(1, weight=4)
        self.provider_tab.rowconfigure(0, weight=1)

        left = ttk.Frame(self.provider_tab)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.provider_tree = ttk.Treeview(
            left,
            columns=("name", "model", "backend", "secret"),
            show="headings",
            selectmode="browse",
        )
        for key, title, width in (
            ("name", "名称", 170),
            ("model", "模型", 160),
            ("backend", "凭据来源", 90),
            ("secret", "状态", 90),
        ):
            self.provider_tree.heading(key, text=title)
            self.provider_tree.column(key, width=width, minwidth=70)
        self.provider_tree.grid(row=0, column=0, sticky="nsew")
        self.provider_tree.bind("<<TreeviewSelect>>", self._on_provider_selected)
        scroll = ttk.Scrollbar(left, command=self.provider_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.provider_tree.configure(yscrollcommand=scroll.set)
        buttons = ttk.Frame(left)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="新建", command=self._clear_provider_form).pack(side=tk.LEFT)
        ttk.Button(buttons, text="删除", command=self._delete_provider).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="测试连接", command=self._test_selected_provider).pack(side=tk.LEFT)

        editor = ttk.LabelFrame(self.provider_tab, text="供应商配置", padding=12)
        editor.grid(row=0, column=1, sticky="nsew")
        editor.columnconfigure(1, weight=1)

        self.form_vars: dict[str, tk.StringVar] = {
            "preset": tk.StringVar(value=PRESETS[0].name),
            "provider_id": tk.StringVar(),
            "display_name": tk.StringVar(),
            "base_url": tk.StringVar(),
            "model": tk.StringVar(),
            "secret_backend": tk.StringVar(value="session"),
            "secret_ref": tk.StringVar(),
            "credential": tk.StringVar(),
            "auth_header": tk.StringVar(value="Authorization"),
            "auth_prefix": tk.StringVar(value="Bearer "),
            "timeout_seconds": tk.StringVar(value="90"),
        }
        rows = [
            ("预设", "preset"),
            ("Provider ID", "provider_id"),
            ("显示名称", "display_name"),
            ("Base URL", "base_url"),
            ("模型 ID", "model"),
            ("凭据来源", "secret_backend"),
            ("凭据引用", "secret_ref"),
            ("API Key（写入后清空）", "credential"),
            ("鉴权 Header", "auth_header"),
            ("鉴权前缀", "auth_prefix"),
            ("超时秒数", "timeout_seconds"),
        ]
        self.form_vars["provider_id"].trace_add("write", self._provider_id_changed)
        self.form_widgets: dict[str, tk.Widget] = {}
        for row, (label, key) in enumerate(rows):
            ttk.Label(editor, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 8))
            if key == "preset":
                widget: tk.Widget = ttk.Combobox(
                    editor,
                    textvariable=self.form_vars[key],
                    values=[preset.name for preset in PRESETS],
                    state="readonly",
                )
                widget.bind("<<ComboboxSelected>>", self._apply_preset)
            elif key == "secret_backend":
                widget = ttk.Combobox(
                    editor,
                    textvariable=self.form_vars[key],
                    values=("none", "session", "environment", "keyring"),
                    state="readonly",
                )
                widget.bind("<<ComboboxSelected>>", self._sync_credential_controls)
            elif key == "auth_header":
                widget = ttk.Combobox(
                    editor,
                    textvariable=self.form_vars[key],
                    values=("Authorization", "api-key", "x-api-key"),
                    state="readonly",
                )
            elif key == "auth_prefix":
                widget = ttk.Combobox(
                    editor,
                    textvariable=self.form_vars[key],
                    values=("Bearer ", ""),
                    state="readonly",
                )
            else:
                widget = ttk.Entry(
                    editor,
                    textvariable=self.form_vars[key],
                    show="*" if key == "credential" else "",
                )
            widget.grid(row=row, column=1, sticky="ew", pady=5)
            self.form_widgets[key] = widget
        self.secret_help_var = tk.StringVar()
        ttk.Label(editor, textvariable=self.secret_help_var, wraplength=500).grid(
            row=len(rows), column=0, columnspan=2, sticky="w", pady=(6, 8)
        )
        save_row = ttk.Frame(editor)
        save_row.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="ew")
        ttk.Button(save_row, text="保存配置", command=self._save_provider).pack(side=tk.LEFT)
        ttk.Button(save_row, text="清空密钥输入", command=lambda: self.form_vars["credential"].set("")).pack(
            side=tk.LEFT, padx=8
        )
        self._apply_preset()

    def _build_compare_tab(self) -> None:
        self.compare_tab.columnconfigure(0, weight=1)
        self.compare_tab.columnconfigure(1, weight=3)
        self.compare_tab.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(self.compare_tab, text="测试输入", padding=10)
        controls.grid(row=0, column=0, columnspan=2, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="System Prompt").grid(row=0, column=0, sticky="nw", padx=(0, 8))
        self.system_text = tk.Text(controls, height=3, wrap=tk.WORD)
        self.system_text.grid(row=0, column=1, columnspan=5, sticky="ew")
        ttk.Label(controls, text="User Prompt").grid(row=1, column=0, sticky="nw", padx=(0, 8), pady=(8, 0))
        self.prompt_text = tk.Text(controls, height=7, wrap=tk.WORD)
        self.prompt_text.grid(row=1, column=1, columnspan=5, sticky="ew", pady=(8, 0))
        self.temperature_var = tk.StringVar(value="0.2")
        self.max_tokens_var = tk.StringVar(value="1024")
        self.concurrency_var = tk.StringVar(value="4")
        for column, (label, var) in enumerate(
            (
                ("Temperature", self.temperature_var),
                ("Max tokens", self.max_tokens_var),
                ("并发", self.concurrency_var),
            )
        ):
            ttk.Label(controls, text=label).grid(row=2, column=column * 2, sticky="w", pady=(8, 0))
            ttk.Entry(controls, textvariable=var, width=10).grid(
                row=2, column=column * 2 + 1, sticky="w", pady=(8, 0), padx=(4, 16)
            )
        self.run_button = ttk.Button(controls, text="运行对比", command=self._run_comparison)
        self.run_button.grid(row=3, column=0, pady=(10, 0), sticky="w")
        self.export_button = ttk.Button(
            controls, text="导出结果 JSON", command=self._export_results, state=tk.DISABLED
        )
        self.export_button.grid(row=3, column=1, pady=(10, 0), sticky="w")

        provider_frame = ttk.LabelFrame(self.compare_tab, text="选择供应商（可多选）", padding=8)
        provider_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0), padx=(0, 10))
        provider_frame.rowconfigure(0, weight=1)
        provider_frame.columnconfigure(0, weight=1)
        self.compare_provider_list = tk.Listbox(provider_frame, selectmode=tk.EXTENDED, exportselection=False)
        self.compare_provider_list.grid(row=0, column=0, sticky="nsew")

        result_frame = ttk.LabelFrame(self.compare_tab, text="结果", padding=8)
        result_frame.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        result_frame.rowconfigure(1, weight=1)
        result_frame.columnconfigure(0, weight=1)
        self.result_tree = ttk.Treeview(
            result_frame,
            columns=("provider", "status", "latency", "tokens"),
            show="headings",
            height=6,
        )
        for key, title, width in (
            ("provider", "供应商", 170),
            ("status", "状态", 70),
            ("latency", "延迟(ms)", 90),
            ("tokens", "Tokens", 80),
        ):
            self.result_tree.heading(key, text=title)
            self.result_tree.column(key, width=width)
        self.result_tree.grid(row=0, column=0, sticky="ew")
        self.result_tree.bind("<<TreeviewSelect>>", self._show_result_detail)
        self.result_detail = tk.Text(result_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.result_detail.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    def _load_providers(self) -> None:
        try:
            self.providers = self.store.load()
        except ConfigurationError as exc:
            self.providers = []
            messagebox.showerror("配置错误", str(exc))
        self._refresh_provider_views()

    def _refresh_provider_views(self) -> None:
        selected_id = self._selected_provider_id()
        self.provider_tree.delete(*self.provider_tree.get_children())
        for provider in self.providers:
            status = self.service.secret_manager.status(provider)
            self.provider_tree.insert(
                "",
                tk.END,
                iid=provider.provider_id,
                values=(provider.display_name, provider.model, provider.secret_backend, status),
            )
        self.compare_provider_list.delete(0, tk.END)
        for provider in self.providers:
            self.compare_provider_list.insert(tk.END, f"{provider.display_name} [{provider.model}]")
        if selected_id and self.provider_tree.exists(selected_id):
            self.provider_tree.selection_set(selected_id)

    def _selected_provider_id(self) -> str | None:
        selection = self.provider_tree.selection()
        return selection[0] if selection else None

    def _provider_by_id(self, provider_id: str) -> ProviderConfig | None:
        return next((item for item in self.providers if item.provider_id == provider_id), None)

    def _on_provider_selected(self, _event: object = None) -> None:
        provider_id = self._selected_provider_id()
        if not provider_id:
            return
        provider = self._provider_by_id(provider_id)
        if provider is None:
            return
        for key, value in provider.to_dict().items():
            if key in self.form_vars:
                self.form_vars[key].set(str(value))
        self.form_vars["credential"].set("")
        self._sync_credential_controls()

    def _clear_provider_form(self) -> None:
        self.provider_tree.selection_remove(self.provider_tree.selection())
        self._apply_preset()
        self.form_vars["credential"].set("")

    def _apply_preset(self, _event: object = None) -> None:
        preset = PRESETS_BY_NAME[self.form_vars["preset"].get()]
        self.form_vars["provider_id"].set(preset.provider_id)
        self.form_vars["display_name"].set(preset.display_name)
        self.form_vars["base_url"].set(preset.base_url)
        self.form_vars["model"].set(preset.model)
        self.form_vars["secret_backend"].set(preset.secret_backend)
        self.form_vars["secret_ref"].set(preset.secret_ref)
        self.form_vars["credential"].set("")
        self.form_vars["auth_header"].set("Authorization")
        self.form_vars["auth_prefix"].set("Bearer ")
        self.form_vars["timeout_seconds"].set("90")
        self._sync_credential_controls()

    def _sync_credential_controls(self, _event: object = None) -> None:
        backend = self.form_vars["secret_backend"].get()
        credential_entry = self.form_widgets["credential"]
        if backend in {"none", "environment"}:
            credential_entry.configure(state=tk.DISABLED)
            self.form_vars["credential"].set("")
        else:
            credential_entry.configure(state=tk.NORMAL)
        ref_entry = self.form_widgets["secret_ref"]
        if backend in {"session", "keyring"}:
            self.form_vars["secret_ref"].set(self.form_vars["provider_id"].get().strip().lower())
            ref_entry.configure(state=tk.DISABLED)
        elif backend == "none":
            self.form_vars["secret_ref"].set("")
            ref_entry.configure(state=tk.DISABLED)
        else:
            ref_entry.configure(state=tk.NORMAL)
        help_text = {
            "none": "不发送鉴权 Header，适用于本地无鉴权服务。",
            "session": "密钥只保存在当前进程内存，关闭窗口即消失。",
            "environment": "这里只保存环境变量名；请在启动 GUI 前设置对应环境变量。",
            "keyring": "密钥写入 Windows Credential Manager / macOS Keychain / Linux Secret Service；需要安装 keyring extra。",
        }.get(backend, "")
        self.secret_help_var.set(help_text)

    def _provider_id_changed(self, *_args: object) -> None:
        if self.form_vars["secret_backend"].get() in {"session", "keyring"}:
            self.form_vars["secret_ref"].set(self.form_vars["provider_id"].get().strip().lower())

    def _config_from_form(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id=self.form_vars["provider_id"].get(),
            display_name=self.form_vars["display_name"].get(),
            base_url=self.form_vars["base_url"].get(),
            model=self.form_vars["model"].get(),
            adapter="openai_chat",
            secret_backend=self.form_vars["secret_backend"].get(),
            secret_ref=self.form_vars["secret_ref"].get(),
            auth_header=self.form_vars["auth_header"].get(),
            auth_prefix=self.form_vars["auth_prefix"].get(),
            timeout_seconds=self.form_vars["timeout_seconds"].get(),
        )

    def _save_provider(self) -> None:
        try:
            provider = self._config_from_form()
            credential = self.form_vars["credential"].get()
            current_id = self._selected_provider_id()
            updated = [item for item in self.providers if item.provider_id not in {current_id, provider.provider_id}]
            updated.append(provider)
            self.store.save(updated)
            if credential.strip():
                self.service.secret_manager.set_for_provider(provider, credential)
            self.providers = sorted(updated, key=lambda item: item.provider_id)
            self.form_vars["credential"].set("")
            self._refresh_provider_views()
            self.provider_tree.selection_set(provider.provider_id)
            self.status_var.set(f"已保存 {provider.display_name}；配置文件不包含 API Key")
        except (ConfigurationError, SecretError, OSError) as exc:
            messagebox.showerror("保存失败", redact_text(exc))
        finally:
            self.form_vars["credential"].set("")

    def _delete_provider(self) -> None:
        provider_id = self._selected_provider_id()
        provider = self._provider_by_id(provider_id or "")
        if provider is None:
            messagebox.showinfo("删除", "请先选择供应商。")
            return
        if not messagebox.askyesno("确认删除", f"删除 {provider.display_name} 的配置？"):
            return
        try:
            self.service.secret_manager.delete_for_provider(provider)
        except SecretError:
            pass
        self.providers = [item for item in self.providers if item.provider_id != provider.provider_id]
        self.store.save(self.providers)
        self._refresh_provider_views()
        self._clear_provider_form()

    def _test_selected_provider(self) -> None:
        provider_id = self._selected_provider_id()
        provider = self._provider_by_id(provider_id or "")
        if provider is None:
            messagebox.showinfo("测试连接", "请先选择供应商。")
            return
        options = ComparisonOptions(temperature=0.0, max_tokens=24, max_concurrency=1)
        self._start_task(
            "测试连接",
            lambda: self.service.invoke_one(provider, "Reply with CGKN_PROVIDER_OK only.", options),
            "test_result",
        )

    def _run_comparison(self) -> None:
        indices = list(self.compare_provider_list.curselection())
        if not indices:
            messagebox.showinfo("对比测试", "至少选择一个供应商。")
            return
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showinfo("对比测试", "请输入 User Prompt。")
            return
        try:
            options = ComparisonOptions(
                temperature=self.temperature_var.get(),
                max_tokens=self.max_tokens_var.get(),
                system_prompt=self.system_text.get("1.0", tk.END),
                max_concurrency=self.concurrency_var.get(),
            )
        except ConfigurationError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        selected = [self.providers[index] for index in indices]
        self.latest_selected = selected
        self.latest_options = options
        self.latest_results = []
        self.result_tree.delete(*self.result_tree.get_children())
        self._set_result_detail("")
        self.export_button.configure(state=tk.DISABLED)
        self._start_task(
            "运行对比",
            lambda: self.service.compare(selected, prompt, options),
            "comparison_result",
        )

    def _start_task(self, label: str, callback: Callable[[], Any], event_name: str) -> None:
        if self._busy:
            messagebox.showinfo(label, "已有任务正在运行。")
            return
        self._busy = True
        self.run_button.configure(state=tk.DISABLED)
        self.status_var.set(f"{label}中…")

        def worker() -> None:
            try:
                self._events.put((event_name, callback()))
            except Exception as exc:
                self._events.put(("task_error", redact_text(exc)))

        threading.Thread(target=worker, daemon=True, name="provider-lab-ui-worker").start()

    def _poll_events(self) -> None:
        try:
            while True:
                event_name, payload = self._events.get_nowait()
                self._busy = False
                self.run_button.configure(state=tk.NORMAL)
                if event_name == "test_result":
                    result: ProviderResult = payload
                    if result.status == "ok":
                        messagebox.showinfo(
                            "测试成功", f"{result.display_name} 可用，延迟 {result.latency_ms} ms。"
                        )
                    else:
                        messagebox.showerror("测试失败", result.error)
                    self.status_var.set("连接测试完成")
                elif event_name == "comparison_result":
                    self.latest_results = list(payload)
                    self._render_results()
                    self.export_button.configure(state=tk.NORMAL)
                    ok_count = sum(result.status == "ok" for result in self.latest_results)
                    self.status_var.set(f"对比完成：{ok_count}/{len(self.latest_results)} 成功")
                elif event_name == "task_error":
                    messagebox.showerror("任务失败", str(payload))
                    self.status_var.set("任务失败")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _render_results(self) -> None:
        self.result_tree.delete(*self.result_tree.get_children())
        for result in self.latest_results:
            self.result_tree.insert(
                "",
                tk.END,
                iid=result.provider_id,
                values=(
                    result.display_name,
                    result.status,
                    result.latency_ms,
                    result.total_tokens if result.total_tokens is not None else "-",
                ),
            )
        if self.latest_results:
            first = self.latest_results[0].provider_id
            self.result_tree.selection_set(first)
            self._show_result_detail()

    def _show_result_detail(self, _event: object = None) -> None:
        selection = self.result_tree.selection()
        if not selection:
            return
        result = next((item for item in self.latest_results if item.provider_id == selection[0]), None)
        if result is None:
            return
        blocks = [
            f"供应商：{result.display_name}",
            f"模型：{result.model}",
            f"状态：{result.status}",
            f"延迟：{result.latency_ms} ms",
        ]
        if result.error:
            blocks.extend(["", "错误：", result.error])
        if result.reasoning:
            blocks.extend(["", "Reasoning：", result.reasoning])
        if result.text:
            blocks.extend(["", "输出：", result.text])
        self._set_result_detail("\n".join(blocks))

    def _set_result_detail(self, text: str) -> None:
        self.result_detail.configure(state=tk.NORMAL)
        self.result_detail.delete("1.0", tk.END)
        self.result_detail.insert("1.0", text)
        self.result_detail.configure(state=tk.DISABLED)

    def _export_results(self) -> None:
        if not self.latest_results:
            return
        path = filedialog.asksaveasfilename(
            title="导出对比结果",
            defaultextension=".json",
            filetypes=(("JSON", "*.json"),),
        )
        if not path:
            return
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        try:
            self.service.export_results(
                Path(path),
                self.latest_selected,
                prompt,
                self.latest_options,
                self.latest_results,
            )
            self.status_var.set(f"结果已导出：{path}")
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))


def run_gui() -> None:
    app = ProviderLabApp()
    app.mainloop()
