import subprocess

# ... 在 delete_tifs 函数中 ...

try:
    # 构建 Windows 删除命令
    # /s = 递归子目录, /q = 安静模式不确认, /f = 强制删除只读文件
    cmd_tif = f'del /s /q /f "{os.path.join(proj["path"], "*.tif")}"'
    cmd_tiff = f'del /s /q /f "{os.path.join(proj["path"], "*.tiff")}"'
    
    # 执行命令 (shell=True 允许执行内置命令 del)
    subprocess.run(cmd_tif, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(cmd_tiff, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    messagebox.showinfo("清理完成", "TIF 文件清理指令已执行。")
    self.refresh_single_engineer(engineer_name, detail_win)
except Exception as e:
    messagebox.showerror("删除失败", f"执行删除命令时发生错误:\n{e}")
