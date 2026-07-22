import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timedelta
import threading

def get_dir_size(start_path):
    """递归计算文件夹大小（字节）"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                try:
                    total_size += os.path.getsize(fp)
                except OSError:
                    pass
    return total_size

def format_size(size_in_bytes):
    """将字节转换为人类可读的格式"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} PB"

def get_creation_time(path):
    """获取创建时间"""
    stat = os.stat(path)
    try:
        return stat.st_birthtime
    except AttributeError:
        return stat.st_ctime

class CTDataApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CT 数据容量统计工具 (带尺寸过滤 & 其他分类)")
        self.root.geometry("950x650")
        self.root.configure(bg="#f0f0f0")
        
        self.data = {} # 存储扫描结果
        
        self.setup_ui()

    def setup_ui(self):
        # 顶部控制栏
        top_frame = tk.Frame(self.root, bg="#ffffff", pady=15)
        top_frame.pack(fill=tk.X)

        # 标题
        title_label = tk.Label(top_frame, text="📊 CT 数据统计", font=("Arial", 16, "bold"), bg="#ffffff")
        title_label.pack(side=tk.LEFT, padx=15)

        # 过滤器设置区域
        filter_frame = tk.Frame(top_frame, bg="#ffffff")
        filter_frame.pack(side=tk.LEFT, padx=20)

        self.use_filter_var = tk.BooleanVar(value=False)
        self.filter_checkbox = tk.Checkbutton(
            filter_frame, text="过滤小尺寸工程 (低于阈值不统计)", 
            variable=self.use_filter_var, bg="#ffffff", command=self.toggle_filter_input
        )
        self.filter_checkbox.pack(side=tk.LEFT)

        self.threshold_var = tk.StringVar(value="1.0") # 默认 1.0 GB
        self.threshold_entry = ttk.Entry(filter_frame, textvariable=self.threshold_var, width=5, state=tk.DISABLED)
        self.threshold_entry.pack(side=tk.LEFT, padx=(5, 2))
        
        self.unit_label = tk.Label(filter_frame, text="GB", bg="#ffffff", fg="#888888")
        self.unit_label.pack(side=tk.LEFT)

        # 扫描按钮和状态
        self.scan_btn = ttk.Button(top_frame, text="📁 选择文件夹并扫描", command=self.start_scan)
        self.scan_btn.pack(side=tk.RIGHT, padx=15)

        self.status_var = tk.StringVar(value="请设置过滤条件后点击扫描")
        status_label = tk.Label(top_frame, textvariable=self.status_var, bg="#ffffff", fg="#666666")
        status_label.pack(side=tk.RIGHT, padx=10)

        # 主体内容区 (带滚动条的 Canvas)
        self.canvas = tk.Canvas(self.root, bg="#f0f0f0", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="#f0f0f0")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=10)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def toggle_filter_input(self):
        """根据复选框状态启用/禁用输入框"""
        if self.use_filter_var.get():
            self.threshold_entry.config(state=tk.NORMAL)
            self.unit_label.config(fg="#000000")
        else:
            self.threshold_entry.config(state=tk.DISABLED)
            self.unit_label.config(fg="#888888")

    def start_scan(self):
        # 获取过滤阈值 (字节)
        threshold_bytes = 0
        if self.use_filter_var.get():
            try:
                gb_val = float(self.threshold_var.get())
                threshold_bytes = gb_val * 1024 * 1024 * 1024
            except ValueError:
                messagebox.showerror("输入错误", "请输入有效的数字作为过滤阈值 (例如 1.5)")
                return

        base_dir = filedialog.askdirectory(title="请选择包含所有工程师文件夹的根目录")
        if not base_dir:
            return

        self.scan_btn.config(state=tk.DISABLED)
        self.filter_checkbox.config(state=tk.DISABLED)
        self.threshold_entry.config(state=tk.DISABLED)
        
        self.status_var.set(f"正在扫描: {base_dir}，请耐心等待...")
        
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        threading.Thread(target=self.scan_process, args=(base_dir, threshold_bytes), daemon=True).start()

    def scan_process(self, base_dir, threshold_bytes):
        nasuni_pattern = re.compile(r'^[Nn]_?FACT-\d{6}')
        normal_pattern = re.compile(r'^FACT-\d{6}')
        cutoff_date = datetime.now() - timedelta(days=90)

        self.data = {}
        filtered_count = 0

        try:
            for engineer_name in os.listdir(base_dir):
                eng_path = os.path.join(base_dir, engineer_name)
                if not os.path.isdir(eng_path):
                    continue

                eng_total_size = 0
                standard_projects = []
                other_projects = []
                other_total_size = 0

                for project_name in os.listdir(eng_path):
                    proj_path = os.path.join(eng_path, project_name)
                    if not os.path.isdir(proj_path):
                        continue

                    proj_size = get_dir_size(proj_path)

                    if threshold_bytes > 0 and proj_size < threshold_bytes:
                        filtered_count += 1
                        continue

                    eng_total_size += proj_size

                    ctime = get_creation_time(proj_path)
                    creation_date = datetime.fromtimestamp(ctime)
                    age_status = "> 90 Days" if creation_date < cutoff_date else "<= 90 Days"

                    # 判断是否为标准命名
                    if nasuni_pattern.search(project_name):
                        category = "Nasuni Uploaded"
                        standard_projects.append({
                            'name': project_name, 'category': category, 
                            'age': age_status, 'date': creation_date.strftime('%Y-%m-%d'),
                            'size': proj_size, 'size_str': format_size(proj_size)
                        })
                    elif normal_pattern.search(project_name):
                        category = "Standard CT"
                        standard_projects.append({
                            'name': project_name, 'category': category, 
                            'age': age_status, 'date': creation_date.strftime('%Y-%m-%d'),
                            'size': proj_size, 'size_str': format_size(proj_size)
                        })
                    else:
                        # 归类为 Other (非标准命名)
                        other_total_size += proj_size
                        other_projects.append({
                            'name': project_name, 'category': "Other", 
                            'age': "-", 'date': "-", # Other 类别简化显示
                            'size': proj_size, 'size_str': format_size(proj_size)
                        })

                if standard_projects or other_projects:
                    self.data[engineer_name] = {
                        'total_size': eng_total_size,
                        'total_size_str': format_size(eng_total_size),
                        'standard_projects': standard_projects,
                        'other_projects': other_projects,
                        'other_total_size': other_total_size
                    }

            self.root.after(0, self.render_engineer_cards, filtered_count)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", f"扫描过程中出现错误: {str(e)}"))
            self.root.after(0, self.reset_ui_state)

    def reset_ui_state(self):
        self.scan_btn.config(state=tk.NORMAL)
        self.filter_checkbox.config(state=tk.NORMAL)
        self.toggle_filter_input()
        self.status_var.set("扫描结束或中断")

    def render_engineer_cards(self, filtered_count):
        self.reset_ui_state()
        
        msg = f"扫描完成！共 {len(self.data)} 位工程师。"
        if self.use_filter_var.get():
            msg += f" (已过滤 {filtered_count} 个小尺寸工程)"
        self.status_var.set(msg)

        sorted_engineers = sorted(self.data.items(), key=lambda x: x[1]['total_size'], reverse=True)

        row, col = 0, 0
        max_cols = 4

        for eng_name, info in sorted_engineers:
            card = tk.Frame(self.scrollable_frame, bg="#ffffff", bd=1, relief="ridge", padx=15, pady=15)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

            card.bind("<Enter>", lambda e, c=card: c.configure(bg="#f9f9f9", cursor="hand2"))
            card.bind("<Leave>", lambda e, c=card: c.configure(bg="#ffffff"))

            icon_label = tk.Label(card, text="🧑‍💻", font=("Arial", 36), bg=card.cget("bg"))
            icon_label.pack()

            name_label = tk.Label(card, text=eng_name, font=("Arial", 12, "bold"), bg=card.cget("bg"))
            name_label.pack(pady=(5, 0))

            size_label = tk.Label(card, text=info['total_size_str'], font=("Arial", 10), fg="#0066cc", bg=card.cget("bg"))
            size_label.pack(pady=(0, 5))

            for widget in (card, icon_label, name_label, size_label):
                widget.bind("<Button-1>", lambda e, name=eng_name: self.show_details(name))

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def show_details(self, engineer_name):
        info = self.data[engineer_name]
        
        detail_win = tk.Toplevel(self.root)
        detail_win.title(f"{engineer_name} 的详细数据")
        detail_win.geometry("850x450")
        
        summary_frame = tk.Frame(detail_win, pady=10, padx=10)
        summary_frame.pack(fill=tk.X)
        tk.Label(summary_frame, text=f"工程师: {engineer_name}", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        tk.Label(summary_frame, text=f"总占用: {info['total_size_str']}", font=("Arial", 12), fg="#0066cc").pack(side=tk.RIGHT)

        # 使用 tree 模式显示数据 (移除 show="headings"，保留默认的树状列 #0)
        columns = ("Category", "Age", "Date", "Size")
        tree = ttk.Treeview(detail_win, columns=columns)
        
        # 配置树状列 (用于显示文件名和折叠图标)
        tree.heading("#0", text="工程文件夹 / 文件名")
        tree.column("#0", width=300, anchor="w")

        tree.heading("Category", text="类别")
        tree.heading("Age", text="时间标记")
        tree.heading("Date", text="创建日期")
        tree.heading("Size", text="大小")

        tree.column("Category", width=150)
        tree.column("Age", width=100)
        tree.column("Date", width=100)
        tree.column("Size", width=100, anchor="e")

        # 1. 插入标准命名的工程 (直接在根节点显示)
        sorted_standard = sorted(info['standard_projects'], key=lambda x: x['size'], reverse=True)
        for proj in sorted_standard:
            tree.insert("", tk.END, text=proj['name'], values=(
                proj['category'], 
                proj['age'], 
                proj['date'], 
                proj['size_str']
            ))

        # 2. 如果有 Other 类别，创建一个父节点
        if info['other_projects']:
            other_title = f"📁 Others (非标准命名) - 共 {len(info['other_projects'])} 个"
            other_size_str = format_size(info['other_total_size'])
            
            # 插入父节点 (默认折叠)
            other_node = tree.insert("", tk.END, text=other_title, values=(
                "Other Group", "-", "-", other_size_str
            ), tags=('other_group',))

            # 设置父节点样式 (加粗)
            tree.tag_configure('other_group', font=('Arial', 10, 'bold'), background='#f5f5f5')

            # 将具体的 Other 文件夹作为子节点插入
            sorted_others = sorted(info['other_projects'], key=lambda x: x['size'], reverse=True)
            for proj in sorted_others:
                # 子节点只显示文件名和大小，其他列留空
                tree.insert(other_node, tk.END, text=f"📄 {proj['name']}", values=(
                    "", "", "", proj['size_str']
                ))

        scrollbar = ttk.Scrollbar(detail_win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=(0, 10))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=(0, 10))

if __name__ == "__main__":
    root = tk.Tk()
    app = CTDataApp(root)
    root.mainloop()
