"""Single-file native desktop entry point."""
import sys


def main(argv=None):
    """转交给 native_window.main（延迟导入：跑 --esptool 时不必拉起整个窗口栈）。"""
    from native_window import main as native_main
    return native_main(argv)


def _run_esptool(rest):
    """`程序.exe --esptool ...` → 本进程直接当 esptool 用。

    为什么不是另装 esptool：客户机上没有 Python，也没有 PlatformIO。
    烧录器需要的是一个能跑 esptool 的解释器，而冻结后的程序自己就是解释器。
    """
    # --windowed 打包时 sys.stdout 是 None；父进程用管道接管时才拿得到 fd 1。
    for name, fd in (('stdout', 1), ('stderr', 2)):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(fd, 'w', buffering=1, encoding='utf-8',
                                        errors='replace', closefd=False))
            except OSError:
                pass
    import esptool
    sys.argv = ['esptool'] + list(rest)
    try:
        esptool.main()
    except SystemExit as exit_error:
        code = exit_error.code if isinstance(exit_error.code, int) else 1
        sys.exit(code)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--esptool':
        _run_esptool(sys.argv[2:])
        sys.exit(0)
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
