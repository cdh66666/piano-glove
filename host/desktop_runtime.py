"""Single-file native desktop entry point."""
import sys
from native_window import main

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import customer_runtime as runtime
        (runtime.data_directory() / 'desktop-error.txt').write_text(str(error), encoding='utf-8')
        if sys.stderr:
            print('启动失败：'+str(error), file=sys.stderr)
        if not any(flag in sys.argv for flag in ('--no-open','--self-test','--list-ports')):
            import tkinter as tk
            from tkinter import messagebox
            root=tk.Tk(); root.withdraw()
            messagebox.showerror('钢琴手套','软件未能启动：'+str(error),parent=root)
            root.destroy()
        sys.exit(1)