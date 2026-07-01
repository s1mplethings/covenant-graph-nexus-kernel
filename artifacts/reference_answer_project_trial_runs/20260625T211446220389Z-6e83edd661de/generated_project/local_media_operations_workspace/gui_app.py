from __future__ import annotations

import tkinter as tk
import orchestrator


def build_app() -> tk.Tk:
    root = tk.Tk()
    root.title("CGKN Degraded Pipeline")
    label = tk.Label(root, text="Shared orchestrator/stages pipeline. Delivery evidence is still required.")
    label.pack()
    button = tk.Button(root, text="Run degraded pipeline", command=lambda: orchestrator.run())
    button.pack()
    return root


if __name__ == "__main__":
    build_app().mainloop()
