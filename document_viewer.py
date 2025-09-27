import sys
import webbrowser
from pathlib import Path
import fitz  # PyMuPDF
from typing import Optional, List
import zipfile
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QPushButton, QLabel, QFileDialog, QScrollArea,
    QMessageBox, QListWidgetItem, QSlider, QTextEdit, QAbstractItemView,
    QDockWidget, QSplitter, QFrame, QGridLayout, QLineEdit,
    QPinchGesture, QDialog
)
from PyQt6.QtGui import QPixmap, QImage, QIcon, QTransform, QDragEnterEvent, QDropEvent, QAction, QKeySequence, QCursor
from PyQt6.QtCore import Qt, QSize, QMimeData, pyqtSignal, QPoint, QEvent

class DraggableListWidget(QListWidget):
    """ドラッグ&ドロップで項目の順序を変更できるリストウィジェット"""
    
    itemsReordered = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        
    def dropEvent(self, event: QDropEvent):
        super().dropEvent(event)
        self.itemsReordered.emit()

class DraggableLabel(QLabel):
    """ドラッグで移動可能で、リンクを検出する画像表示ラベル"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._is_dragging = False
        self._drag_start_pos = None
        self._main_window = None

    def set_main_window(self, window):
        """メインウィンドウへの参照を設定"""
        self._main_window = window

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self._is_dragging = False
            
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            if not self._is_dragging and self._drag_start_pos:
                delta = event.pos() - self._drag_start_pos
                if (delta.x()**2 + delta.y()**2) > 25:
                    self._is_dragging = True
                    self.last_global_pos = event.globalPosition()
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
            
            if self._is_dragging:
                parent = self.parent()
                while parent and not isinstance(parent, QScrollArea):
                    parent = parent.parent()
                
                if parent and isinstance(parent, QScrollArea):
                    current_global_pos = event.globalPosition()
                    delta = current_global_pos - self.last_global_pos
                    
                    h_bar = parent.horizontalScrollBar()
                    v_bar = parent.verticalScrollBar()
                    
                    h_bar.setValue(h_bar.value() - int(delta.x()))
                    v_bar.setValue(v_bar.value() - int(delta.y()))
                    
                    self.last_global_pos = current_global_pos
        else:
            if self._main_window and self._main_window.is_over_link(event.pos()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._is_dragging and self._drag_start_pos:
                delta = event.pos() - self._drag_start_pos
                if (delta.x()**2 + delta.y()**2) <= 25:
                    if self._main_window:
                        self._main_window.handle_link_click(event.pos())
            
            self._is_dragging = False
            self._drag_start_pos = None
            if self._main_window and self._main_window.is_over_link(event.pos()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
        
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            parent = self.parent()
            while parent and not isinstance(parent, QScrollArea):
                parent = parent.parent()
            
            if parent and isinstance(parent, QScrollArea):
                h_bar = parent.horizontalScrollBar()
                v_bar = parent.verticalScrollBar()
                h_bar.setValue((h_bar.maximum() + h_bar.minimum()) // 2)
                v_bar.setValue((v_bar.maximum() + v_bar.minimum()) // 2)

class PinchZoomScrollArea(QScrollArea):
    """ピンチ操作でズームができるスクロールエリア"""
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.viewport().grabGesture(Qt.GestureType.PinchGesture)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Gesture:
            gesture = event.gesture(Qt.GestureType.PinchGesture)
            if gesture:
                self.handle_pinch_gesture(gesture)
                return True
        return super().event(event)

    def handle_pinch_gesture(self, gesture: QPinchGesture):
        if gesture.state() == Qt.GestureState.GestureUpdated:
            zoom_center = gesture.centerPoint()
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            old_h_val = h_bar.value()
            old_v_val = v_bar.value()
            scale_factor = gesture.scaleFactor()
            self.main_window.set_zoom_by_factor(scale_factor, zoom_center)
            QApplication.processEvents()
            if h_bar.maximum() > 0:
                h_bar.setValue(int(old_h_val * scale_factor + zoom_center.x() * (scale_factor - 1)))
            if v_bar.maximum() > 0:
                v_bar.setValue(int(old_v_val * scale_factor + zoom_center.y() * (scale_factor - 1)))
        return True

class UsageDialog(QDialog):
    """使い方を表示するダイアログ"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Document Viewer 使い方")
        self.setModal(True)
        self.resize(700, 600)
        
        layout = QVBoxLayout(self)
        
        usage_text = """
【Document Viewer 使い方】

■ 基本操作
• フォルダ選択: 左上の「フォルダ選択」ボタンでドキュメントフォルダを指定
• 対応形式: PDF、画像(PNG/JPG/BMP/GIF/TIFF)、Office文書(DOCX/XLSX/PPTX)
• ファイル切替: 左側リストをクリック、または矢印キーで前後の文書へ移動

■ ビューア操作
• ズーム: マウスホイール、ピンチジェスチャー（MacOSだけ？）、またはコントロールパネルのスライダー
• 移動: ドラッグで画面をスクロール
• 中央表示: ダブルクリック、またはSpaceキー
• 回転: コントロールパネルの回転ボタン、またはCtrl+L/R
• リンク: PDF内のリンクをクリックで開く

■ キーボードショートカット
• →/← : 前後のページ
• Ctrl+→/← : 前後の文書
• Ctrl++/- : ズームイン/アウト
• Ctrl+0 : ズーム100%
• Ctrl+L/R : 左右回転
• Ctrl+B : サイドバー表示/非表示
• Ctrl+P : コントロールパネル表示/非表示
• Space : 中央表示

■ その他の機能
• ファイル順序変更: 左側リストでドラッグ&ドロップ
• ページ移動: コントロールパネルでページ番号を直接入力

問い合わせ先：瀬谷 勇太　✉️ Yuuta_Seya@member.metro.tokyo.jp
        """
        
        text_edit = QTextEdit()
        text_edit.setPlainText(usage_text)
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                color: #333;
                padding: 15px;
                font-size: 13px;
                font-family: 'Yu Gothic UI', 'Meiryo', sans-serif;
                border: none;
            }
        """)
        layout.addWidget(text_edit)
        
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        close_button.setStyleSheet("padding: 8px 20px; font-size: 13px;")
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignCenter)

class DocumentViewer(QMainWindow):
    """
    多機能ドキュメントビューアアプリケーション
    PDF、画像、MS Officeファイルをサポート
    """
    def __init__(self):
        super().__init__()
        
        # --- Application State ---
        self.current_folder_path = None
        self.document_files = []
        self.current_document = None
        self.current_document_index = 0
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.rotation_angle = 0
        self.current_page_links = []
        self.link_hit_areas = []
        self.transform_matrix = None
        self.viewer_widget = None
        self.viewer_label = None
        self.sidebar_visible = True
        self.is_office_document = False
        
        self.init_ui()
        self.setup_shortcuts()
        
        # 全画面表示に設定
        self.showMaximized()
        
        if hasattr(self, 'zoom_slider'):
            self.zoom_slider.setValue(int(self.zoom_level * 100))

    def init_ui(self):
        """Initialize the UI components and layout."""
        self.setWindowTitle("Document Viewer v1.1 　　|　   →/← : 前後のページ    　|　    Ctrl+→/← : 前後の文書   　|　   Ctrl+ +/- : ズームイン/アウト    　:　  新宿山吹ICT委員会")
        self.setGeometry(100, 100, 1500, 900)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # --- Left Sidebar ---
        self.sidebar_widget = QWidget()
        self.sidebar_widget.setMinimumWidth(300)
        self.sidebar_widget.setMaximumWidth(600)
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(8)
        
        sidebar_header = QWidget()
        header_layout = QHBoxLayout(sidebar_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.folder_button = QPushButton("フォルダ選択")
        self.folder_button.setStyleSheet("padding: 10px; font-size: 14px; font-weight: bold;")
        self.folder_button.clicked.connect(self.select_folder)
        header_layout.addWidget(self.folder_button)
        
        self.hide_sidebar_btn = QPushButton("◀")
        self.hide_sidebar_btn.setFixedSize(30, 30)
        self.hide_sidebar_btn.clicked.connect(self.toggle_sidebar)
        self.hide_sidebar_btn.setToolTip("サイドバーを隠す")
        header_layout.addWidget(self.hide_sidebar_btn)
        
        sidebar_layout.addWidget(sidebar_header)

        instructions = QLabel("ドラッグ&ドロップで順序変更可能")
        instructions.setStyleSheet("color: #666; font-size: 11px; padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        sidebar_layout.addWidget(instructions)

        self.file_list_widget = DraggableListWidget()
        self.file_list_widget.setStyleSheet("""
            QListWidget { font-size: 13px; border: 1px solid #ddd; border-radius: 5px; }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #eee; }
            QListWidget::item:selected { background-color: #3498db; color: white; }
            QListWidget::item:hover { background-color: #ecf0f1; }
        """)
        self.file_list_widget.itemClicked.connect(self.handle_file_selection)
        self.file_list_widget.itemsReordered.connect(self.handle_list_reorder)
        sidebar_layout.addWidget(self.file_list_widget)

        # --- Right Pane (Viewer) ---
        self.viewer_container = QWidget()
        viewer_layout = QVBoxLayout(self.viewer_container)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.setSpacing(0)
        
        self.show_sidebar_btn = QPushButton("▶ サイドバー表示")
        self.show_sidebar_btn.setStyleSheet("padding: 5px 10px; margin: 5px;")
        self.show_sidebar_btn.clicked.connect(self.toggle_sidebar)
        self.show_sidebar_btn.hide()
        viewer_layout.addWidget(self.show_sidebar_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        
        # 使い方の説明テキストを作成（初期表示用）
        usage_text = """
【Document Viewer 使い方】

■ 基本操作
• フォルダ選択: 左上の「フォルダ選択」ボタンでドキュメントフォルダを指定
• 対応形式: PDF、画像(PNG/JPG/BMP/GIF/TIFF)、Office文書(DOCX/XLSX/PPTX)
• ファイル切替: 左側リストをクリック、または矢印キーで前後の文書へ移動

■ ビューア操作
• ズーム: マウスホイール、ピンチジェスチャー、またはコントロールパネルのスライダー
• 移動: ドラッグで画面をスクロール
• 中央表示: ダブルクリック、またはSpaceキー
• 回転: コントロールパネルの回転ボタン、またはCtrl+L/R
• リンク: PDF内のリンクをクリックで開く

■ キーボードショートカット
• →/← : 前後のページ
• Ctrl+→/← : 前後の文書
• Ctrl++/- : ズームイン/アウト
• Ctrl+0 : ズーム100%
• Ctrl+L/R : 左右回転
• Ctrl+B : サイドバー表示/非表示
• Ctrl+P : コントロールパネル表示/非表示
• Space : 中央表示

■ その他の機能
• ファイル順序変更: 左側リストでドラッグ&ドロップ
• ページ移動: コントロールパネルでページ番号を直接入力

問い合わせ先：瀬谷 勇太　✉️ Yuuta_Seya@member.metro.tokyo.jp
        """
        
        self.viewer_instructions = QTextEdit()
        self.viewer_instructions.setPlainText(usage_text)
        self.viewer_instructions.setReadOnly(True)
        self.viewer_instructions.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                color: #333;
                padding: 15px;
                font-size: 12px;
                font-family: 'Yu Gothic UI', 'Meiryo', sans-serif;
                border: none;
            }
        """)
        self.viewer_instructions.setMaximumHeight(400)
        viewer_layout.addWidget(self.viewer_instructions)
        
        # Use custom scroll area for pinch zoom
        self.scroll_area = PinchZoomScrollArea(self)
        self.scroll_area.setStyleSheet("background-color: #f5f5f5;")
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        viewer_layout.addWidget(self.scroll_area)
        
        self.create_viewer_label()
        
        self.splitter.addWidget(self.sidebar_widget)
        self.splitter.addWidget(self.viewer_container)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        
        self.create_floating_control_panel()
        self.create_menu_bar()
        self.update_navigation_controls()

    def create_floating_control_panel(self):
        """コンパクトなフローティングコントロールパネルを作成（右下に配置）"""
        self.control_panel = QDockWidget("コントロール", self)
        self.control_panel.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.control_panel.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | 
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        
        container = QWidget()
        self.control_panel.setWidget(container)
        
        main_panel_layout = QVBoxLayout(container)
        main_panel_layout.setContentsMargins(8, 8, 8, 8)
        main_panel_layout.setSpacing(8)
        
        self.prev_doc_button = QPushButton("前の文書")
        self.next_doc_button = QPushButton("次の文書")
        self.prev_button = QPushButton("前へ")
        self.next_button = QPushButton("次へ")
        self.page_input = QLineEdit()
        self.page_total_label = QLabel("/ -")
        self.zoom_out_button = QPushButton("-")
        
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(25)
        self.zoom_slider.setMaximum(400)
        self.zoom_slider.setSingleStep(5)
        self.zoom_slider.setPageStep(25)
        self.zoom_slider.setTickInterval(25)
        self.zoom_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        
        self.zoom_in_button = QPushButton("+")
        self.zoom_percent_label = QLabel("100%")
        self.rotate_left_button = QPushButton("左回転")
        self.rotate_right_button = QPushButton("右回転")
        self.reset_view_button = QPushButton("リセット")
        
        self.prev_doc_button.clicked.connect(self.show_previous_document)
        self.next_doc_button.clicked.connect(self.show_next_document)
        self.prev_button.clicked.connect(self.show_previous_page)
        self.next_button.clicked.connect(self.show_next_page)
        self.page_input.returnPressed.connect(self.go_to_page)
        self.zoom_out_button.clicked.connect(self.zoom_out)
        self.zoom_in_button.clicked.connect(self.zoom_in)
        self.zoom_slider.valueChanged.connect(self.handle_zoom_change)
        self.rotate_left_button.clicked.connect(self.rotate_left)
        self.rotate_right_button.clicked.connect(self.rotate_right)
        self.reset_view_button.clicked.connect(self.reset_view)
        
        doc_nav_frame = self.create_styled_frame()
        doc_nav_layout = QHBoxLayout(doc_nav_frame)
        doc_nav_layout.addWidget(self.prev_doc_button)
        doc_nav_layout.addWidget(self.next_doc_button)
        main_panel_layout.addWidget(doc_nav_frame)
        
        page_nav_frame = self.create_styled_frame()
        page_nav_layout = QVBoxLayout(page_nav_frame)
        page_btn_layout = QHBoxLayout()
        page_btn_layout.addWidget(self.prev_button)
        page_btn_layout.addWidget(self.page_input)
        page_btn_layout.addWidget(self.page_total_label)
        page_btn_layout.addWidget(self.next_button)
        page_nav_layout.addLayout(page_btn_layout)
        main_panel_layout.addWidget(page_nav_frame)
        
        zoom_frame = self.create_styled_frame()
        zoom_layout = QVBoxLayout(zoom_frame)
        zoom_controls_layout = QHBoxLayout()
        zoom_controls_layout.addWidget(self.zoom_out_button)
        zoom_controls_layout.addWidget(self.zoom_slider)
        zoom_controls_layout.addWidget(self.zoom_in_button)
        zoom_controls_layout.addWidget(self.zoom_percent_label)
        zoom_layout.addLayout(zoom_controls_layout)
        main_panel_layout.addWidget(zoom_frame)
        
        rotation_frame = self.create_styled_frame()
        rotation_btn_layout = QHBoxLayout(rotation_frame)
        rotation_btn_layout.addWidget(self.rotate_left_button)
        rotation_btn_layout.addWidget(self.reset_view_button)
        rotation_btn_layout.addWidget(self.rotate_right_button)
        main_panel_layout.addWidget(rotation_frame)
        
        shortcut_frame = self.create_styled_frame(is_help=True)
        shortcut_layout = QVBoxLayout(shortcut_frame)
        shortcut_title = QLabel("ショートカット")
        shortcuts_text = QLabel("Ctrl+B : サイドバー\nCtrl+P : パネル")
        shortcut_layout.addWidget(shortcut_title)
        shortcut_layout.addWidget(shortcuts_text)
        main_panel_layout.addWidget(shortcut_frame)
        
        main_panel_layout.addStretch()
        
        self.style_control_panel_widgets()
        
        # 右下に配置するための設定
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.control_panel)
        self.control_panel.setFloating(True)
        self.control_panel.resize(280, 380)
        
        # ウィンドウが表示された後に位置を調整
        QApplication.processEvents()
        screen_geometry = QApplication.primaryScreen().geometry()
        self.control_panel.move(
            screen_geometry.width() - 300,  # 右端から300px
            screen_geometry.height() - 450  # 下端から450px
        )

    def show_usage(self):
        """使い方ダイアログを表示"""
        dialog = UsageDialog(self)
        dialog.exec()

    def create_menu_bar(self):
        menubar = self.menuBar()
        view_menu = menubar.addMenu('表示')      
        actions_data = [
            ('サイドバー表示/非表示', 'Ctrl+B', self.toggle_sidebar),
            ('コントロールパネル表示/非表示', 'Ctrl+P', self.toggle_control_panel),
            ('中央表示', 'Space', self.center_view),
            ('使い方', 'F1', self.show_usage) 
        ]
        
        for text, shortcut, func in actions_data:
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(func)
            view_menu.addAction(action)

    def open_document(self, file_path):
        """ドキュメントを開く"""
        try:
            if self.current_document:
                self.current_document.close()
                self.current_document = None
            if file_path.suffix.lower() in ['.docx', '.xlsx', '.pptx']:
                self.is_office_document = True
                self.display_office_document(file_path)
                self.viewer_instructions.hide()
            else:
                self.is_office_document = False
                self.create_viewer_label()
                self.viewer_instructions.hide()
                self.current_document = fitz.open(str(file_path))
                self.current_page_index = 0
                self.render_current_page()
        except Exception as e:
            self.show_error_message(f"'{file_path.name}'を開けませんでした:\n{e}")
            self.clear_viewer()
        finally:
            self.update_navigation_controls()

    def clear_viewer(self):
        """ビューアをクリアして使い方を表示"""
        if self.current_document:
            self.current_document.close()
            self.current_document = None
        self.create_viewer_label()
        self.viewer_instructions.show()
        self.is_office_document = False
        self.viewer_label.setText("")

    def create_styled_frame(self, is_help=False):
        frame = QFrame()
        if is_help:
            frame.setStyleSheet("""
                QFrame { background-color: #f8f9fa; border: 2px solid #6c757d; border-radius: 4px; padding: 8px; }
            """)
        else:
            frame.setStyleSheet("""
                QFrame { background-color: white; border: 1px solid #ddd; border-radius: 4px; padding: 6px; }
            """)
        return frame

    def style_control_panel_widgets(self):
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_input.setFixedWidth(50)
        self.page_input.setStyleSheet("font-weight: bold; font-size: 12px; padding: 4px;")
        self.page_total_label.setStyleSheet("font-size: 12px; padding-left: 0px;")
        
        self.zoom_out_button.setFixedSize(28, 28)
        self.zoom_out_button.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.zoom_in_button.setFixedSize(28, 28)
        self.zoom_in_button.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        self.zoom_percent_label.setFixedWidth(45)
        self.zoom_percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_percent_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        
        self.reset_view_button.setFixedWidth(80)
        
        self.control_panel.setStyleSheet("""
            QDockWidget { font-family: 'Segoe UI', 'Yu Gothic UI', sans-serif; }
            QDockWidget::title { background-color: #2c3e50; color: white; padding: 6px; font-size: 13px; font-weight: bold; }
            QPushButton { padding: 6px 10px; border: 1px solid #ddd; border-radius: 3px; background-color: #f8f9fa; font-size: 12px; }
            QPushButton:hover { background-color: #e9ecef; border-color: #adb5bd; }
            QPushButton:pressed { background-color: #dee2e6; }
            QPushButton:disabled { background-color: #e9ecef; color: #6c757d; }
        """)

    def setup_shortcuts(self):
        actions = [
            ("Next Page", "Right", self.show_next_page),
            ("Previous Page", "Left", self.show_previous_page),
            ("Next Doc", "Ctrl+Right", self.show_next_document),
            ("Previous Doc", "Ctrl+Left", self.show_previous_document),
            ("Zoom In", "Ctrl++", self.zoom_in),
            ("Zoom Out", "Ctrl+-", self.zoom_out),
            ("Reset Zoom", "Ctrl+0", self.reset_zoom_to_100),
            ("Rotate Left", "Ctrl+L", self.rotate_left),
            ("Rotate Right", "Ctrl+R", self.rotate_right),
            ("Center View", "Space", self.center_view)
        ]
        
        for name, shortcut, func in actions:
            action = QAction(name, self)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(func)
            self.addAction(action)

    def center_view(self):
        if hasattr(self, 'viewer_label') and isinstance(self.viewer_label, DraggableLabel):
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            h_bar.setValue((h_bar.maximum() + h_bar.minimum()) // 2)
            v_bar.setValue((v_bar.maximum() + v_bar.minimum()) // 2)

    def go_to_page(self):
        if not self.current_document or self.is_office_document: return
        try:
            target_page_one_based = int(self.page_input.text())
            target_page_zero_based = target_page_one_based - 1
            if 0 <= target_page_zero_based < self.current_document.page_count:
                self.current_page_index = target_page_zero_based
                self.render_current_page()
                self.update_navigation_controls()
            else:
                raise ValueError("Page number out of range")
        except (ValueError, IndexError):
            QMessageBox.warning(self, "無効なページ", "有効なページ番号を入力してください。")
            self.update_navigation_controls()
        self.page_input.clearFocus()

    def reset_zoom_to_100(self):
        """ズームを100%にリセット"""
        self.zoom_level = 1.0
        self.zoom_slider.setValue(100)
        if not self.is_office_document and self.current_document:
            self.render_current_page()

    def toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible
        self.sidebar_widget.setVisible(self.sidebar_visible)
        self.show_sidebar_btn.setVisible(not self.sidebar_visible)

    def toggle_control_panel(self):
        self.control_panel.setVisible(not self.control_panel.isVisible())

    def create_viewer_label(self):
        if self.viewer_widget and self.viewer_widget != self.scroll_area.widget():
            self.viewer_widget.deleteLater()
        self.viewer_label = DraggableLabel(self.scroll_area)
        self.viewer_label.set_main_window(self)
        self.viewer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewer_widget = self.viewer_label
        self.scroll_area.setWidget(self.viewer_label)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewer_label.setStyleSheet("font-size: 18px; color: #7f8c8d; padding: 20px;")

    def create_text_viewer(self):
        if self.viewer_widget and self.viewer_widget != self.scroll_area.widget():
            self.viewer_widget.deleteLater()
        self.text_viewer = QTextEdit()
        self.text_viewer.setReadOnly(True)
        self.text_viewer.setStyleSheet("font-size: 12px; padding: 10px; background-color: white;")
        self.viewer_widget = self.text_viewer
        self.scroll_area.setWidget(self.text_viewer)
        self.scroll_area.setWidgetResizable(True)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder:
            self.current_folder_path = Path(folder)
            self.load_files()

    def load_files(self):
        self.file_list_widget.clear()
        self.document_files = []
        supported_extensions = ['.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.docx', '.xlsx', '.pptx']
        try:
            sorted_paths = sorted(self.current_folder_path.iterdir())
            for path in sorted_paths:
                if path.is_file() and path.suffix.lower() in supported_extensions:
                    self.document_files.append(path)
                    if path.suffix.lower() == '.pdf': icon = "PDF"
                    elif path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff']: icon = "IMG"
                    else: icon = "DOC"
                    item = QListWidgetItem(f"[{icon}] {path.name}")
                    self.file_list_widget.addItem(item)
            if self.document_files:
                self.current_document_index = 0
                self.file_list_widget.setCurrentRow(0)
                self.open_document(self.document_files[0])
            else:
                self.clear_viewer()
                self.viewer_label.setText("対応ファイルが見つかりませんでした")
        except Exception as e:
            self.show_error_message(f"フォルダの読み込みに失敗: {e}")

    def handle_list_reorder(self):
        new_order = []
        for i in range(self.file_list_widget.count()):
            item_text = self.file_list_widget.item(i).text()
            filename = item_text.split('] ', 1)[1] if '] ' in item_text else item_text
            for file_path in self.document_files:
                if file_path.name == filename:
                    new_order.append(file_path)
                    break
        self.document_files = new_order
        if self.current_document:
            current_file_path = self.document_files[self.current_document_index]
            try:
                self.current_document_index = new_order.index(current_file_path)
            except ValueError:
                self.current_document_index = 0

    def handle_file_selection(self, item):
        selected_index = self.file_list_widget.row(item)
        if 0 <= selected_index < len(self.document_files):
            self.current_document_index = selected_index
            self.open_document(self.document_files[selected_index])

    def show_previous_document(self):
        if self.current_document_index > 0:
            self.current_document_index -= 1
            self.file_list_widget.setCurrentRow(self.current_document_index)
            self.open_document(self.document_files[self.current_document_index])

    def show_next_document(self):
        if self.current_document_index < len(self.document_files) - 1:
            self.current_document_index += 1
            self.file_list_widget.setCurrentRow(self.current_document_index)
            self.open_document(self.document_files[self.current_document_index])

    def display_office_document(self, file_path):
        try:
            self.create_text_viewer()
            content = ""
            if file_path.suffix.lower() == '.docx': content = self.extract_docx_text(file_path)
            elif file_path.suffix.lower() == '.xlsx': content = self.extract_xlsx_text(file_path)
            elif file_path.suffix.lower() == '.pptx': content = self.extract_pptx_text(file_path)
            self.text_viewer.setPlainText(content)
        except Exception as e:
            self.create_viewer_label()
            self.viewer_label.setText(f"Office文書の読み込みエラー:\n{str(e)}")

    def extract_docx_text(self, file_path):
        text_content = []
        try:
            with zipfile.ZipFile(file_path, 'r') as docx:
                xml_content = docx.read('word/document.xml')
                tree = ET.fromstring(xml_content)
                namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                for paragraph in tree.findall('.//w:p', namespaces):
                    texts = [t.text for t in paragraph.findall('.//w:t', namespaces) if t.text]
                    if texts: text_content.append(''.join(texts))
        except Exception as e: return f"DOCX読み込みエラー: {str(e)}"
        return '\n'.join(text_content) if text_content else "テキストが見つかりませんでした"

    def extract_xlsx_text(self, file_path):
        text_content = ["=== Excel ファイル内容 (簡易表示) ===\n"]
        try:
            with zipfile.ZipFile(file_path, 'r') as xlsx:
                shared_strings = []
                if 'xl/sharedStrings.xml' in xlsx.namelist():
                    xml_content = xlsx.read('xl/sharedStrings.xml')
                    tree = ET.fromstring(xml_content)
                    shared_strings = [t.text for si in tree.findall('.//{*}si') if (t := si.find('.//{*}t')) is not None and t.text]
                if 'xl/workbook.xml' in xlsx.namelist():
                    workbook_xml = xlsx.read('xl/workbook.xml')
                    wb_tree = ET.fromstring(workbook_xml)
                    sheets = wb_tree.findall('.//{*}sheet')
                    for i, sheet in enumerate(sheets, 1):
                        sheet_name = sheet.get('name', f'Sheet{i}')
                        text_content.append(f"\n【シート: {sheet_name}】")
                        sheet_file = f'xl/worksheets/sheet{i}.xml'
                        if sheet_file in xlsx.namelist():
                            sheet_xml = xlsx.read(sheet_file)
                            sheet_tree = ET.fromstring(sheet_xml)
                            for row_count, row in enumerate(sheet_tree.findall('.//{*}row')):
                                if row_count > 100:
                                    text_content.append("... (以降省略)")
                                    break
                                cell_values = []
                                for cell in row.findall('.//{*}c'):
                                    v_elem = cell.find('.//{*}v')
                                    if v_elem is not None and v_elem.text:
                                        if cell.get('t') == 's':
                                            idx = int(v_elem.text)
                                            if idx < len(shared_strings): cell_values.append(shared_strings[idx])
                                        else: cell_values.append(v_elem.text)
                                if cell_values: text_content.append(' | '.join(cell_values))
        except Exception as e: return f"XLSX読み込みエラー: {str(e)}"
        return '\n'.join(text_content) if len(text_content) > 1 else "データが見つかりませんでした"

    def extract_pptx_text(self, file_path):
        text_content = ["=== PowerPoint プレゼンテーション内容 ===\n"]
        try:
            with zipfile.ZipFile(file_path, 'r') as pptx:
                slide_num = 1
                while True:
                    slide_file = f'ppt/slides/slide{slide_num}.xml'
                    if slide_file not in pptx.namelist(): break
                    text_content.append(f"\n【スライド {slide_num}】")
                    xml_content = pptx.read(slide_file)
                    tree = ET.fromstring(xml_content)
                    texts = [elem.text for elem in tree.iter() if elem.tag.endswith('}t') and elem.text]
                    text_content.append('\n'.join(texts) if texts else "(テキストなし)")
                    slide_num += 1
        except Exception as e: return f"PPTX読み込みエラー: {str(e)}"
        return '\n'.join(text_content) if len(text_content) > 1 else "スライドが見つかりませんでした"

    def render_current_page(self):
        if not self.current_document or self.current_document.is_closed: return
        try:
            page = self.current_document.load_page(self.current_page_index)
            self.transform_matrix = fitz.Matrix(self.zoom_level, self.zoom_level).prerotate(self.rotation_angle)
            pix = page.get_pixmap(matrix=self.transform_matrix)
            self.current_page_links = page.get_links()
            self.link_hit_areas = []
            for ln in self.current_page_links:
                r = ln.get('from') or ln.get('rect')
                if r:
                    dev_rect = fitz.Rect(r) * self.transform_matrix
                    self.link_hit_areas.append((dev_rect, ln))
            img_format = QImage.Format.Format_RGB888 if pix.n - pix.alpha < 4 else QImage.Format.Format_RGBA8888
            qimage = QImage(pix.samples, pix.width, pix.height, pix.stride, img_format)
            if not isinstance(self.viewer_widget, DraggableLabel): 
                self.create_viewer_label()
            self.viewer_label.setStyleSheet("background: transparent;")
            self.viewer_label.setPixmap(QPixmap.fromImage(qimage))
            self.viewer_label.adjustSize()
            QApplication.processEvents()
        except Exception as e:
            self.show_error_message(f"ページ {self.current_page_index + 1} の表示に失敗:\n{e}")
            self.clear_viewer()

    def is_over_link(self, pos: QPoint) -> bool:
        if not self.link_hit_areas: return False
        p = fitz.Point(pos.x(), pos.y())
        return any(dev_rect.contains(p) for dev_rect, _ in self.link_hit_areas)

    def handle_link_click(self, pos: QPoint) -> bool:
        if not self.link_hit_areas: return False
        p = fitz.Point(pos.x(), pos.y())
        for dev_rect, ln in self.link_hit_areas:
            if dev_rect.contains(p):
                kind = ln.get('kind')
                if kind == fitz.LINK_URI:
                    uri = ln.get('uri')
                    if uri:
                        webbrowser.open(uri)
                        return True
                elif kind == fitz.LINK_GOTO:
                    page_num = ln.get('page')
                    if isinstance(page_num, int) and page_num >= 0:
                        self.current_page_index = page_num
                        self.render_current_page()
                        self.update_navigation_controls()
                        return True
        return False

    def set_zoom_by_factor(self, factor, center_pos):
        """スケール係数に基づいてズームレベルを設定する"""
        new_zoom = self.zoom_level * factor
        new_zoom = max(0.25, min(new_zoom, 4.0))
        self.zoom_level = new_zoom
        self.zoom_slider.setValue(int(self.zoom_level * 100))
        if not self.is_office_document and self.current_document:
            self.render_current_page()

    def handle_zoom_change(self, value):
        """Handle zoom slider changes."""
        self.zoom_level = value / 100.0
        self.zoom_percent_label.setText(f"{value}%")
        if not self.is_office_document and self.current_document:
            self.render_current_page()

    def zoom_in(self):
        """Zoom in by 5%."""
        new_value = min(self.zoom_slider.value() + 5, 400)
        self.zoom_slider.setValue(new_value)

    def zoom_out(self):
        """Zoom out by 5%."""
        new_value = max(self.zoom_slider.value() - 5, 25)
        self.zoom_slider.setValue(new_value)

    def rotate_left(self):
        if not self.is_office_document:
            self.rotation_angle = (self.rotation_angle - 90) % 360
            if self.current_document: self.render_current_page()

    def rotate_right(self):
        if not self.is_office_document:
            self.rotation_angle = (self.rotation_angle + 90) % 360
            if self.current_document: self.render_current_page()

    def reset_view(self):
        """Reset zoom and rotation to default."""
        self.rotation_angle = 0
        self.zoom_level = 1.0
        self.zoom_slider.setValue(100)
        if not self.is_office_document and self.current_document:
            self.render_current_page()

    def show_previous_page(self):
        if not self.is_office_document and self.current_document and self.current_page_index > 0:
            self.current_page_index -= 1
            self.render_current_page()
            self.update_navigation_controls()

    def show_next_page(self):
        if not self.is_office_document and self.current_document and self.current_page_index < self.current_document.page_count - 1:
            self.current_page_index += 1
            self.render_current_page()
            self.update_navigation_controls()

    def update_navigation_controls(self):
        self.prev_doc_button.setEnabled(self.current_document_index > 0)
        self.next_doc_button.setEnabled(self.current_document_index < len(self.document_files) - 1)
        if self.is_office_document:
            self.page_input.setText("Office")
            self.page_input.setEnabled(False)
            self.page_total_label.setText("")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
        elif self.current_document and not self.current_document.is_closed and self.current_document.page_count > 0:
            total_pages = self.current_document.page_count
            self.page_input.setText(str(self.current_page_index + 1))
            self.page_total_label.setText(f"/ {total_pages}")
            self.page_input.setEnabled(True)
            self.prev_button.setEnabled(self.current_page_index > 0)
            self.next_button.setEnabled(self.current_page_index < total_pages - 1)
        else:
            self.page_input.setText("-")
            self.page_total_label.setText("/ -")
            self.page_input.setEnabled(False)
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)

    def show_error_message(self, message):
        QMessageBox.critical(self, "エラー", message)

    def closeEvent(self, event):
        if self.current_document: self.current_document.close()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    viewer = DocumentViewer()
    viewer.show()
    sys.exit(app.exec())