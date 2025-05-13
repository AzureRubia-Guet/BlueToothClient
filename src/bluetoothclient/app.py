import asyncio
import logging
import json
from importlib.resources import files
from sys import stdout

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from bluetoothclient.resources.esp_ouis import ouis as esp_ouis
from bluetoothclient.bluetooth_manager import BluetoothManager


def setup_logging() -> None:
    """配置日志系统"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(stdout)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)


class BluetoothClient(toga.App):
    """蓝牙控制客户端主应用类"""

    def __init__(self) -> None:
        super().__init__()
        # 蓝牙配置
        self.service_uuid: str = "000000ff-0000-1000-8000-00805f9b34fb"
        self.char_uuid: str = "0000ff01-0000-1000-8000-00805f9b34fb"
        self.target_name: str = "ESP"
        self.esp_ouis: set[str] = esp_ouis
        self.bluetooth_manager = BluetoothManager(self.service_uuid, self.char_uuid, self.target_name, self.esp_ouis)
        self.event_loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()

        # UI组件声明
        self.device_list: list[toga.Box] = list()
        self.left_content: toga.Box | None = None
        self.right_content: toga.Box | None = None
        self.scan_button: toga.Button | None = None
        self.connect_button: toga.Button | None = None
        self.disconnect_button: toga.Button | None = None
        self.device_table: toga.Table | None = None
        self.device_status: toga.Box | None = None
        self.split: toga.SplitContainer | None = None
        self.status_table: toga.Table | None = None

        setup_logging()

    def startup(self) -> None:
        """初始化用户界面"""
        # 初始化主容器
        self.split = toga.SplitContainer()

        # 创建左侧面板
        self._create_left_panel()

        # 创建右侧面板
        self._create_right_panel()

        # 配置分栏布局
        self.split.content = [
            (self.left_content, 1),
            (self.right_content, 2),
        ]

        # 主窗口配置
        self.main_window = toga.MainWindow(title="蓝牙控制客户端")
        self.main_window.content = self.split
        self.main_window.on_close = self.on_close
        self.main_window.show()

    def on_close(self, window) -> bool:
        self.event_loop.create_task(self.bluetooth_manager.disconnect())
        return True

    def _create_left_panel(self) -> None:
        """创建左侧面板内容"""
        self.left_content = toga.Box(style=Pack(direction=COLUMN, padding=5))

        # 扫描按钮
        self.scan_button = toga.Button(
            "蓝牙扫描", style=Pack(padding=5), on_press=self.scan_bluetooth
        )

        # 设备表格
        self.device_table = toga.Table(
            headings=["名称", "MAC"],
            data=[],
            accessors=["name", "mac"],
            style=Pack(width=280),
        )

        # 连接按钮
        self.connect_button = toga.Button(
            "蓝牙连接", style=Pack(padding=5), on_press=self.connect_bluetooth
        )

        # 断开按钮
        self.disconnect_button = toga.Button(
            "蓝牙断开", style=Pack(padding=5), on_press=self.disconnect_bluetooth
        )

        # 添加组件到左侧面板
        self.left_content.add(
            self.scan_button,
            self.device_table,
            self.connect_button,
            self.disconnect_button,
        )

    def _create_right_panel(self) -> None:
        """创建右侧面板内容"""
        self.right_content = toga.Box(style=Pack(direction=COLUMN, padding=10))

        # 创建控制面板
        self._create_control_panels()

        # 创建状态表
        self._create_status_table()

        # 添加组件到右侧面板
        self.right_content.add(*self.device_list)

    def _create_control_panels(self) -> None:
        """创建设备控制面板"""

        resource_path = files("bluetoothclient.resources") / "device.json"
        with resource_path.open(encoding='utf-8') as file:
            device_data = json.load(file)

        for device in device_data:
            self.device_list.append(toga.Box(style=Pack(direction=ROW)))
            self.device_list[-1].add(
                toga.Label(device["device_name"], style=Pack(padding=(8, 5))),
                *self._create_control_buttons(
                    [button["command"] for button in device["buttons"]],
                    [button["option"] for button in device["buttons"]]
                )
            )

    def _create_control_buttons(
            self, commands: list[int], labels: list[str]
    ) -> list[toga.Button]:
        """创建控制按钮组"""
        return [
            toga.Button(
                label, style=Pack(padding=5), on_press=self.create_control_handler(cmd)
            )
            for cmd, label in zip(commands, labels)
        ]

    def _create_status_table(self) -> None:
        """创建设备状态表"""
        self.status_table = toga.Table(
            headings=["灯光", "风扇", "电热器"],
            data=[{"light": "-", "fan": "-", "heater": "-"}],
            accessors=["light", "fan", "heater"],
            style=Pack(width=280),
        )
        self.device_status = toga.Box(style=Pack(direction=COLUMN))
        self.device_status.add(
            toga.Label("设备状态", style=Pack(padding=(7, 5))), self.status_table
        )

    def create_control_handler(self, command_value: int):
        """生成控制按钮处理器"""

        async def handler(widget: toga.Widget) -> None:
            if await self.bluetooth_manager.send_command(command_value):
                self.logger.info(f"发送控制命令: {command_value} 成功")
            else:
                await self.main_window.dialog(toga.ErrorDialog("错误", "设备未连接或发送失败"))

        return handler

    def scan_bluetooth(self, widget: toga.Widget) -> None:
        """执行蓝牙扫描"""

        async def start_scan() -> None:
            matched = await self.bluetooth_manager.scan_devices()

            if self.device_table:
                self.device_table.data = matched

            if not matched:
                await self.main_window.dialog(
                    toga.InfoDialog("提示", "未找到目标设备")
                )

        self.event_loop.create_task(start_scan())

    def connect_bluetooth(self, widget: toga.Widget) -> None:
        """连接设备"""

        async def start_connect() -> None:
            if not self.device_table or not self.device_table.selection:
                await self.main_window.dialog(
                    toga.ErrorDialog("错误", "请先选择要连接的设备")
                )
                return

            address = self.device_table.selection.mac
            if await self.bluetooth_manager.connect_to_device(address):
                await self.main_window.dialog(
                    toga.InfoDialog("连接状态", "连接成功")
                )
            else:
                await self.main_window.dialog(toga.ErrorDialog("错误", "连接失败"))

        self.event_loop.create_task(start_connect())

    def disconnect_bluetooth(self, widget: toga.Widget) -> None:
        """断开连接"""

        async def start_disconnect() -> None:
            if await self.bluetooth_manager.disconnect():
                await self.main_window.dialog(
                    toga.InfoDialog("连接状态", "已断开连接")
                )
                self._update_status("-", "-", "-")
            else:
                await self.main_window.dialog(
                    toga.ErrorDialog("错误", "断开失败")
                )

        self.event_loop.create_task(start_disconnect())

    def _update_status(self, light: str, fan: str, heater: str) -> None:
        """更新状态显示"""
        if self.status_table:
            self.status_table.data.clear()
            self.status_table.data.append(
                {"light": light, "fan": fan, "heater": heater}
            )


def main() -> BluetoothClient:
    """应用入口"""
    return BluetoothClient()