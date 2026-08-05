import os
import re
import shutil
import tkinter as tk
from tkinter import ttk, filedialog
import tkinter.messagebox as messagebox
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import platform
import subprocess

def get_dir_size(start_path):
    total_size = 0
    dirs_to_process = [start_path]
    while dirs_to_process:
        current_dir = dirs_to_process.pop()
        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_file():
                        total_size += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir():
                        dirs_to_process.append(entry.path)
        except OSError:
            pass 
    return total_size

def format_size(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} PB"

def get_creation_time(path):
    stat = os.stat(path)
    try:
        return stat.st_birthtime
    except AttributeError:
        return stat.st_ctime

def get_age_status_and_tag(creation_date, now):
    days_diff = (now - creation_date).days
    if days_diff <= 14:
        return "🟢 <= 14 Days", "color_green"
    elif days_diff <= 30:
        return "🟢 15-30 Days", "color_green"
    elif days_diff <= 90:
        return "🟡 31-90 Days", "color_yellow"
    elif days_diff <= 180:
        return "🟣 91-180 Days", "color_purple"
    else:
        return "🔴 > 180 Days", "color_red"

class CTDataApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CT 数据容量统计工具 (智能穿透 & TIF清理版)")
        self.root.geometry("1000x650")
        self.root.configure(bg="#f0f0f0")
        
        self.data = {} 
        self.tif_scanned = False
        self.last_base_dir = ""
        self.last_threshold_bytes = 0
        self.last_filtered_count = 0
        
        self.setup_ui()

    def setup_ui(self):
        top_frame = tk.Frame(self.root, bg="#ffffff", pady=15)
        top_frame.pack(fill=tk.X)

        title_label = tk.Label(top_frame, text="📊 CT 数据统计", font=("Arial", 16, "bold"), bg="#ffffff")
        title_label.pack(side=tk.LEFT, padx=15)

        filter_frame = tk.Frame(top_frame, bg="#ffffff")
        filter_frame.pack(side=tk.LEFT, padx=20)

        self.use_filter_var = tk.BooleanVar(value=False)
        self.filter_checkbox = tk.Checkbutton(
            filter_frame, text="过滤小尺寸工程 (低于阈值不统计)", 
            variable=self.use_filter_var, bg="#ffffff", command=self.toggle_filter_input
        )
        self.filter_checkbox.pack(side=tk.LEFT)

        self.threshold_var = tk.StringVar(value="1.0") 
        self.threshold_entry = ttk.Entry(filter_frame, textvariable=self.threshold_var, width=5, state=tk.DISABLED)
        self.threshold_entry.pack(side=tk.LEFT, padx=(5, 2))
        
        self.unit_label = tk.Label(filter_frame, text="GB", bg="#ffffff", fg="#888888")
        self.unit_label.pack(side=tk.LEFT)

        btn_frame = tk.Frame(top_frame, bg="#ffffff")
        btn_frame.pack(side=tk.RIGHT, padx=15)

        self.scan_btn = ttk.Button(btn_frame, text="📁 选择文件夹并扫描", command=self.start_scan)
        self.scan_btn.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))

        self.scan_tif_btn = ttk.Button(btn_frame, text="🔍 扫描大工程 TIF (>50GB)", command=self.start_tif_scan, state=tk.DISABLED)
        self.scan_tif_btn.pack(side=tk.TOP, fill=tk.X)

        self.status_var = tk.StringVar(value="请设置过滤条件后点击扫描")
        status_label = tk.Label(top_frame, textvariable=self.status_var, bg="#ffffff", fg="#666666")
        status_label.pack(side=tk.RIGHT, padx=10)

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
        if self.use_filter_var.get():
            self.threshold_entry.config(state=tk.NORMAL)
            self.unit_label.config(fg="#000000")
        else:
            self.threshold_entry.config(state=tk.DISABLED)
            self.unit_label.config(fg="#888888")

    def start_scan(self):
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

        self.last_base_dir = base_dir
        self.last_threshold_bytes = threshold_bytes
        self.tif_scanned = False
        self.scan_tif_btn.config(state=tk.DISABLED)

        self.scan_btn.config(state=tk.DISABLED)
        self.filter_checkbox.config(state=tk.DISABLED)
        self.threshold_entry.config(state=tk.DISABLED)
        
        self.status_var.set(f"正在初始化扫描: {base_dir}...")
        
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        threading.Thread(target=self.scan_manager, args=(base_dir, threshold_bytes), daemon=True).start()

    def process_single_engineer(self, base_dir, engineer_name, threshold_bytes, now_time, nasuni_pattern):
        eng_path = os.path.join(base_dir, engineer_name)
        
        eng_total_size = 0
        waiting_projects = []
        waiting_total_size = 0
        nasuni_projects = []
        nasuni_total_size = 0
        other_projects = []
        other_total_size = 0
        local_filtered_count = 0

        try:
            items_in_eng_dir = os.listdir(eng_path)
        except PermissionError:
            return engineer_name, None, 0 

        for item in items_in_eng_dir:
            item_path = os.path.join(eng_path, item)
            
            if os.path.isfile(item_path):
                try:
                    file_size = os.path.getsize(item_path)
                except OSError:
                    file_size = 0
                    
                other_total_size += file_size
                eng_total_size += file_size
                other_projects.append({
                    'name': f"📄 {item}", 'path': item_path,
                    'age': "-", 'date': "-", 'tag': "",
                    'size': file_size, 'size_str': format_size(file_size), 'is_dir': False
                })
                continue

            if os.path.isdir(item_path):
                if nasuni_pattern.search(item) or "FACT" in item:
                    proj_size = get_dir_size(item_path)
                    if threshold_bytes > 0 and proj_size < threshold_bytes:
                        local_filtered_count += 1
                        continue

                    eng_total_size += proj_size
                    ctime = get_creation_time(item_path)
                    creation_date = datetime.fromtimestamp(ctime)
                    age_status, color_tag = get_age_status_and_tag(creation_date, now_time)

                    proj_info = {
                        'name': item, 'path': item_path,
                        'age': age_status, 'date': creation_date.strftime('%Y-%m-%d'),
                        'tag': color_tag, 'size': proj_size, 'size_str': format_size(proj_size), 'is_dir': True
                    }

                    if nasuni_pattern.search(item):
                        nasuni_total_size += proj_size
                        nasuni_projects.append(proj_info)
                    else:
                        waiting_total_size += proj_size
                        waiting_projects.append(proj_info)
                else:
                    try:
                        sub_items = os.listdir(item_path)
                    except PermissionError:
                        continue

                    for sub_item in sub_items:
                        sub_path = os.path.join(item_path, sub_item)
                        
                        if os.path.isdir(sub_path):
                            proj_size = get_dir_size(sub_path)
                            if threshold_bytes > 0 and proj_size < threshold_bytes:
                                local_filtered_count += 1
                                continue
                                
                            eng_total_size += proj_size
                            ctime = get_creation_time(sub_path)
                            creation_date = datetime.fromtimestamp(ctime)
                            
                            display_name = f"{item} / {sub_item}"

                            if nasuni_pattern.search(sub_item) or "FACT" in sub_item:
                                age_status, color_tag = get_age_status_and_tag(creation_date, now_time)
                                proj_info = {
                                    'name': display_name, 'path': sub_path,
                                    'age': age_status, 'date': creation_date.strftime('%Y-%m-%d'),
                                    'tag': color_tag, 'size': proj_size, 'size_str': format_size(proj_size), 'is_dir': True
                                }

                                if nasuni_pattern.search(sub_item):
                                    nasuni_total_size += proj_size
                                    nasuni_projects.append(proj_info)
                                else:
                                    waiting_total_size += proj_size
                                    waiting_projects.append(proj_info)
                            else:
                                other_total_size += proj_size
                                other_projects.append({
                                    'name': f"📁 {display_name}", 'path': sub_path,
                                    'age': "-", 'date': "-", 'tag': "",
                                    'size': proj_size, 'size_str': format_size(proj_size), 'is_dir': True
                                })
                        
                        elif os.path.isfile(sub_path):
                            try:
                                file_size = os.path.getsize(sub_path)
                            except OSError:
                                file_size = 0
                            eng_total_size += file_size
                            other_total_size += file_size

        result_data = {
            'total_size': eng_total_size,
            'total_size_str': format_size(eng_total_size),
            'waiting_projects': waiting_projects,
            'waiting_total_size': waiting_total_size,
            'nasuni_projects': nasuni_projects,
            'nasuni_total_size': nasuni_total_size,
            'other_projects': other_projects,
            'other_total_size': other_total_size
        }
        
        return engineer_name, result_data, local_filtered_count

    def scan_manager(self, base_dir, threshold_bytes):
        nasuni_pattern = re.compile(r'[Nn][-_\s]?FACT')
        now_time = datetime.now()

        self.data = {}
        total_filtered_count = 0

        try:
            engineers = [d for d in os.listdir(base_dir) 
                         if not d.startswith('.') 
                         and d not in ['System Volume Information', '$RECYCLE.BIN']
                         and os.path.isdir(os.path.join(base_dir, d))]
            
            total_engineers = len(engineers)
            completed_engineers = 0

            with ThreadPoolExecutor(max_workers=16) as executor:
                future_to_eng = {
                    executor.submit(self.process_single_engineer, base_dir, eng, threshold_bytes, now_time, nasuni_pattern): eng 
                    for eng in engineers
                }

                for future in as_completed(future_to_eng):
                    eng_name = future_to_eng[future]
                    try:
                        name, result_data, local_filtered = future.result()
                        if result_data is not None:
                            self.data[name] = result_data
                            total_filtered_count += local_filtered
                    except Exception as exc:
                        print(f"{eng_name} 扫描出错: {exc}")
                    
                    completed_engineers += 1
                    self.root.after(0, self.update_progress_ui, completed_engineers, total_engineers, eng_name)

            self.last_filtered_count = total_filtered_count
            self.root.after(0, self.render_engineer_cards, total_filtered_count)
            
        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("严重错误", f"扫描过程中出现异常: {str(err)}"))
            self.root.after(0, self.reset_ui_state)

    def start_tif_scan(self):
        self.scan_tif_btn.config(state=tk.DISABLED)
        self.scan_btn.config(state=tk.DISABLED)
        self.status_var.set("正在扫描大于 50GB 的工程寻找 TIF 文件，请稍候...")
        threading.Thread(target=self.tif_scan_process, daemon=True).start()

    def get_tif_size_in_dir(self, start_path):
        tif_size = 0
        dirs_to_process = [start_path]
        while dirs_to_process:
            current_dir = dirs_to_process.pop()
            try:
                with os.scandir(current_dir) as it:
                    for entry in it:
                        if entry.is_symlink():
                            continue
                        if entry.is_file():
                            filename_lower = entry.name.lower()
                            if filename_lower.endswith(('.tif', '.tiff')) and \
                               "bright" not in filename_lower and "dark" not in filename_lower:
                                tif_size += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir():
                            dirs_to_process.append(entry.path)
            except OSError:
                pass
        return tif_size

    def tif_scan_process(self):
        threshold_50gb = 50 * 1024 * 1024 * 1024
        
        for eng_name, info in self.data.items():
            for category in ['waiting_projects', 'nasuni_projects', 'other_projects']:
                for proj in info[category]:
                    if proj.get('is_dir', False) and proj['size'] >= threshold_50gb:
                        proj['tif_size'] = self.get_tif_size_in_dir(proj['path'])
                    else:
                        proj['tif_size'] = 0

        self.tif_scanned = True
        self.root.after(0, self.on_tif_scan_complete)

    def on_tif_scan_complete(self):
        self.scan_btn.config(state=tk.NORMAL)
        self.scan_tif_btn.config(state=tk.NORMAL, text="✅ TIF 扫描已完成")
        self.status_var.set("TIF 扫描完成！现在可以使用右键菜单删除 TIF。")
        messagebox.showinfo("扫描完成", "TIF 文件扫描完毕，您现在可以在详情页右键删除 TIF 文件。")

    def update_progress_ui(self, current, total, last_completed):
        self.status_var.set(f"正在扫描: {current} / {total} (刚刚完成: {last_completed})")

    def reset_ui_state(self):
        self.scan_btn.config(state=tk.NORMAL)
        self.filter_checkbox.config(state=tk.NORMAL)
        self.toggle_filter_input()
        self.status_var.set("扫描结束或中断")

    def render_engineer_cards(self, filtered_count):
        self.reset_ui_state()
        self.scan_tif_btn.config(state=tk.NORMAL) 
        if self.tif_scanned:
            self.scan_tif_btn.config(text="✅ TIF 扫描已完成")
        else:
            self.scan_tif_btn.config(text="🔍 扫描大工程 TIF (>50GB)")
        
        msg = f"扫描完成！共 {len(self.data)} 位工程师。"
        if self.use_filter_var.get():
            msg += f" (已过滤 {filtered_count} 个小尺寸工程)"
        self.status_var.set(msg)

        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

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

    def show_progress_dialog(self, title, message):
        prog_win = tk.Toplevel(self.root)
        prog_win.title(title)
        prog_win.geometry("350x120")
        prog_win.transient(self.root) 
        prog_win.grab_set() 
        
        prog_win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (350 // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (120 // 2)
        prog_win.geometry(f"+{x}+{y}")

        tk.Label(prog_win, text=message, font=("Arial", 10), pady=15).pack()
        
        progress = ttk.Progressbar(prog_win, orient="horizontal", length=280, mode="indeterminate")
        progress.pack(pady=10)
        progress.start(15) 
        
        return prog_win

    # --- 修改：单点刷新逻辑，增加回调支持 ---
    def refresh_single_engineer(self, eng_name, callback=None):
        nasuni_pattern = re.compile(r'[Nn][-_\s]?FACT')
        now_time = datetime.now()
        
        self.status_var.set(f"正在更新 {eng_name} 的数据...")
        self.root.update()

        _, result_data, _ = self.process_single_engineer(
            self.last_base_dir, eng_name, self.last_threshold_bytes, now_time, nasuni_pattern
        )

        if result_data:
            self.data[eng_name] = result_data
        else:
            if eng_name in self.data:
                del self.data[eng_name]

        self.render_engineer_cards(self.last_filtered_count)
        
        # 如果有回调函数（用于刷新详情页），则执行
        if callback:
            callback()

    def show_details(self, engineer_name):
        # 确保数据存在
        if engineer_name not in self.data:
            return
            
        detail_win = tk.Toplevel(self.root)
        detail_win.title(f"{engineer_name} 的详细数据 (双击打开，右键菜单)")
        detail_win.geometry("850x450")
        
        summary_frame = tk.Frame(detail_win, pady=10, padx=10)
        summary_frame.pack(fill=tk.X)
        
        name_label = tk.Label(summary_frame, text=f"工程师: {engineer_name}", font=("Arial", 12, "bold"))
        name_label.pack(side=tk.LEFT)
        
        size_label = tk.Label(summary_frame, text="", font=("Arial", 12), fg="#0066cc")
        size_label.pack(side=tk.RIGHT)

        columns = ("Age", "Date", "Size")
        tree = ttk.Treeview(detail_win, columns=columns)
        
        tree.heading("#0", text="工程文件夹 / 文件名")
        tree.column("#0", width=420, anchor="w")

        tree.heading("Age", text="时间标记")
        tree.heading("Date", text="创建日期")
        tree.heading("Size", text="大小")

        tree.column("Age", width=130)
        tree.column("Date", width=100)
        tree.column("Size", width=100, anchor="e")

        tree.tag_configure('group_node', font=('Arial', 10, 'bold'), background='#f5f5f5')
        tree.tag_configure('color_green', foreground='#008000') 
        tree.tag_configure('color_yellow', foreground='#cc8800') 
        tree.tag_configure('color_purple', foreground='#800080') 
        tree.tag_configure('color_red', foreground='#cc0000') 

        node_data = {}

        # --- 新增：提取填充 Treeview 的独立函数 ---
        def populate_treeview():
            # 1. 清空现有的所有节点
            for item in tree.get_children():
                tree.delete(item)
            node_data.clear()

            # 2. 获取最新数据
            if engineer_name not in self.data:
                detail_win.destroy() # 如果数据被删空了，直接关闭窗口
                return
                
            info = self.data[engineer_name]
            size_label.config(text=f"总占用: {info['total_size_str']}")

            def insert_projects(parent_node, projects_list):
                sorted_projs = sorted(projects_list, key=lambda x: x['size'], reverse=True)
                for proj in sorted_projs:
                    tags = (proj['tag'],) if proj.get('tag') else ()
                    name_display = f"📁 {proj['name']}" if proj.get('is_dir', True) else proj['name']
                    
                    if self.tif_scanned and proj.get('tif_size', 0) > 0:
                        name_display += f" [含TIF: {format_size(proj['tif_size'])}]"

                    iid = tree.insert(parent_node, tk.END, text=name_display, values=(
                        proj['age'], proj['date'], proj['size_str']
                    ), tags=tags)
                    node_data[iid] = proj

            if info['waiting_projects']:
                waiting_title = f"📁 Standard CT (waiting to upload) - 共 {len(info['waiting_projects'])} 个"
                waiting_node = tree.insert("", tk.END, text=waiting_title, values=(
                    "-", "-", format_size(info['waiting_total_size'])
                ), tags=('group_node',))
                insert_projects(waiting_node, info['waiting_projects'])

            if info['nasuni_projects']:
                nasuni_title = f"📁 Standard CT (Nasuni uploaded) - 共 {len(info['nasuni_projects'])} 个"
                nasuni_node = tree.insert("", tk.END, text=nasuni_title, values=(
                    "-", "-", format_size(info['nasuni_total_size'])
                ), tags=('group_node',))
                insert_projects(nasuni_node, info['nasuni_projects'])

            if info['other_projects']:
                other_title = f"📁 Others (非标准命名/零散文件) - 共 {len(info['other_projects'])} 个"
                other_node = tree.insert("", tk.END, text=other_title, values=(
                    "-", "-", format_size(info['other_total_size'])
                ), tags=('group_node',))
                insert_projects(other_node, info['other_projects'])

        # 初始填充数据
        populate_treeview()

        scrollbar = ttk.Scrollbar(detail_win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=(0, 10))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=(0, 10))

        def open_path(path_to_open):
            if os.path.exists(path_to_open):
                try:
                    if platform.system() == "Windows":
                        os.startfile(path_to_open)
                    elif platform.system() == "Darwin":
                        subprocess.Popen(["open", path_to_open])
                    else:
                        subprocess.Popen(["xdg-open", path_to_open])
                except Exception as e:
                    messagebox.showerror("打开失败", f"无法打开路径:\n{path_to_open}\n\n错误信息: {e}")
            else:
                messagebox.showwarning("路径不存在", "该文件或文件夹可能已被移动或删除。")

        def on_double_click(event):
            selected = tree.selection()
            if selected and selected[0] in node_data:
                open_path(node_data[selected[0]]['path'])

        context_menu = tk.Menu(tree, tearoff=0)

        def show_context_menu(event):
            iid = tree.identify_row(event.y)
            if iid and iid in node_data:
                tree.selection_set(iid) 
                proj = node_data[iid]
                
                context_menu.delete(0, tk.END) 
                
                context_menu.add_command(label="📁 打开文件夹所在路径", command=lambda: open_path(proj['path']))
                context_menu.add_separator()
                
                def execute_delete_folder(prog_win):
                    try:
                        if proj.get('is_dir', True):
                            shutil.rmtree(proj['path'])
                        else:
                            os.remove(proj['path'])
                        self.root.after(0, lambda: prog_win.destroy())
                        # 传入 populate_treeview 作为回调，实现无感刷新
                        self.root.after(0, lambda: self.refresh_single_engineer(engineer_name, populate_treeview))
                    except Exception as e:
                        self.root.after(0, lambda: prog_win.destroy())
                        self.root.after(0, lambda err=e: messagebox.showerror("删除失败", f"删除时发生错误:\n{err}"))

                def delete_folder():
                    if messagebox.askyesno("确认删除", f"⚠️ 警告！\n请确认删除文件夹：\n{proj['name']}\n\n此操作不可逆！", icon='warning'):
                        prog_win = self.show_progress_dialog("正在删除", "正在删除数据，请耐心等待...")
                        threading.Thread(target=execute_delete_folder, args=(prog_win,), daemon=True).start()
                            
                context_menu.add_command(label="❌ 删除整个文件夹", command=delete_folder)
                
                def execute_delete_tifs(prog_win):
                    try:
                        deleted_count = 0
                        for root_dir, _, files in os.walk(proj['path']):
                            for file in files:
                                filename_lower = file.lower()
                                if filename_lower.endswith(('.tif', '.tiff')) and \
                                   "bright" not in filename_lower and "dark" not in filename_lower:
                                    os.remove(os.path.join(root_dir, file))
                                    deleted_count += 1
                        
                        self.root.after(0, lambda: prog_win.destroy())
                        self.root.after(0, lambda c=deleted_count: messagebox.showinfo("清理完成", f"成功删除了 {c} 个 TIF 文件。\n(已保留校准文件)"))
                        # 传入 populate_treeview 作为回调，实现无感刷新
                        self.root.after(0, lambda: self.refresh_single_engineer(engineer_name, populate_treeview))
                    except Exception as e:
                        self.root.after(0, lambda: prog_win.destroy())
                        self.root.after(0, lambda err=e: messagebox.showerror("删除失败", f"删除 TIF 时发生错误:\n{err}"))

                def delete_tifs():
                    if messagebox.askyesno("确认删除", f"⚠️ 请确认删除此文件夹中的所有 TIF 文件\n(将自动保留包含 bright 和 dark 的校准文件)：\n{proj['name']}\n\n此操作不可逆！", icon='warning'):
                        prog_win = self.show_progress_dialog("正在清理 TIF", "正在遍历并删除 TIF 文件，请耐心等待...")
                        threading.Thread(target=execute_delete_tifs, args=(prog_win,), daemon=True).start()

                state = tk.NORMAL if (self.tif_scanned and proj.get('is_dir', True)) else tk.DISABLED
                context_menu.add_command(label="🗑️ 删除此文件夹里的 TIF", command=delete_tifs, state=state)

                context_menu.post(event.x_root, event.y_root)

        tree.bind("<Double-1>", on_double_click)
        tree.bind("<Button-3>", show_context_menu)
        if platform.system() == "Darwin":
            tree.bind("<Button-2>", show_context_menu)

if __name__ == "__main__":
    root = tk.Tk()
    app = CTDataApp(root)
    root.mainloop()
