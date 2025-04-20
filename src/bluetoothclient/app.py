import asyncio
import logging
import re
import sys
from typing import Callable, Coroutine, Optional

import toga
from bleak import BleakClient, BleakError, BleakGATTCharacteristic, BleakScanner
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from bluetoothclient.resources.esp_ouis import ouis as esp_ouis


def setup_logging() -> None:
    """配置日志系统"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)


class BluetoothClient(toga.App):
    """蓝牙控制客户端主应用类"""

    def __init__(self) -> None:
        super().__init__()
        # 蓝牙配置
        self.service_uuid = "000000ff-0000-1000-8000-00805f9b34fb"
        self.char_uuid = "0000ff01-0000-1000-8000-00805f9b34fb"
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.client: Optional[BleakClient] = None
        self.target_name: str = "ESP"
        self.esp_ouis: set[str] = esp_ouis
        self.event_loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()

        # UI组件声明
        self.left_content: Optional[toga.Box] = None
        self.right_content: Optional[toga.Box] = None
        self.scan_button: Optional[toga.Button] = None
        self.connect_button: Optional[toga.Button] = None
        self.disconnect_button: Optional[toga.Button] = None
        self.device_table: Optional[toga.Table] = None
        self.light_row: Optional[toga.Box] = None
        self.fan_row: Optional[toga.Box] = None
        self.heater_row: Optional[toga.Box] = None
        self.device_status: Optional[toga.Box] = None
        self.split: Optional[toga.SplitContainer] = None
        self.status_table: Optional[toga.Table] = None

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
            (self.left_content, 1),  # type: ignore
            (self.right_content, 2),  # type: ignore
        ]

        # 主窗口配置
        self.main_window = toga.MainWindow(title="蓝牙控制客户端")
        self.main_window.content = self.split
        self.main_window.show()

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
        self.left_content.add(  # type: ignore
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
        self.right_content.add(  # type: ignore
            self.light_row,  # type: ignore
            self.fan_row,  # type: ignore
            self.heater_row,  # type: ignore
            self.device_status,  # type: ignore
        )

    def _create_control_panels(self) -> None:
        """创建设备控制面板"""
        # 灯光控制
        self.light_row = toga.Box(style=Pack(direction=ROW))
        self.light_row.add(  # type: ignore
            toga.Label("灯光", style=Pack(padding=(8, 5))),
            *self._create_control_buttons(
                [1, 2, 3, 4, 5, 6], ["开", "关", "调亮", "调暗", "呼吸", "流水"]
            ),
        )

        # 风扇控制
        self.fan_row = toga.Box(style=Pack(direction=ROW))
        self.fan_row.add(  # type: ignore
            toga.Label("风扇", style=Pack(padding=(7, 5))),
            *self._create_control_buttons([7, 8, 9, 10], ["开", "关", "加速", "减速"]),
        )

        # 电热器控制
        self.heater_row = toga.Box(style=Pack(direction=ROW))
        self.heater_row.add(  # type: ignore
            toga.Label("电热器", style=Pack(padding=(7, 5))),
            *self._create_control_buttons(
                [15, 16, 17, 18], ["开", "关", "升温", "降温"]
            ),
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
        self.device_status.add(  # type: ignore
            toga.Label("设备状态", style=Pack(padding=(7, 5))), self.status_table
        )

    def create_control_handler(
        self, command_value: int
    ) -> Callable[[toga.Widget], Coroutine]:
        """生成控制按钮处理器"""

        async def handler(widget: toga.Widget) -> None:
            self.logger.info(f"发送控制命令: {command_value}")
            await self.send_command(command_value)

        return handler

    async def send_command(self, value: int) -> bool:
        """发送指令到设备"""
        if not self.client or not self.client.is_connected:
            await self.main_window.dialog(toga.ErrorDialog("错误", "设备未连接"))
            return False

        try:
            await self.client.write_gatt_char(self.char_uuid, bytes([value]))
            self.logger.info(f"成功发送指令: {value}")
            return True
        except BleakError as e:
            self.logger.error(f"发送失败: {str(e)}")
            await self.main_window.dialog(toga.ErrorDialog("错误", f"发送失败: {e}"))
            return False

    def scan_bluetooth(self, widget: toga.Widget) -> None:
        """执行蓝牙扫描"""

        async def start_scan() -> None:
            self.logger.info("开始扫描蓝牙设备...")
            try:
                devices = await BleakScanner.discover()
                matched = [
                    {"name": d.name, "mac": d.address}
                    for d in devices
                    if d.name
                    and (self.target_name in d.name or self.is_esp_device(d.address))
                ]

                if self.device_table:
                    self.device_table.data = matched

                if not matched:
                    await self.main_window.dialog(
                        toga.InfoDialog("提示", "未找到目标设备")
                    )

            except BleakError as e:
                self.logger.error(f"扫描失败: {str(e)}")
                await self.main_window.dialog(
                    toga.ErrorDialog("错误", f"扫描失败: {e}")
                )

        self.event_loop.create_task(start_scan())

    async def connect_to_device(self, address: str) -> bool:
        """连接指定设备"""
        try:
            self.client = BleakClient(address)
            await self.client.connect()

            # 验证服务
            target_service = self.service_uuid.replace("-", "").lower()
            target_char = self.char_uuid.replace("-", "").lower()

            for service in await self.client.get_services():
                if service.uuid.replace("-", "").lower() == target_service:
                    for char in service.characteristics:
                        if char.uuid.replace("-", "").lower() == target_char:
                            await self.client.start_notify(
                                char.uuid, self.notification_handler
                            )
                            return True
            return False
        except BleakError as e:
            self.logger.error(f"连接失败: {str(e)}")
            return False

    def notification_handler(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """处理设备通知"""
        if len(data) == 3:
            status = {
                "light": self._parse_status(data[0], "light"),
                "fan": self._parse_status(data[1], "fan"),
                "heater": self._parse_status(data[2], "heater"),
            }
            self.event_loop.call_soon_threadsafe(
                self._update_status, status["light"], status["fan"], status["heater"]
            )

    def _parse_status(self, value: int, device: str) -> str:
        """解析状态数值"""
        mapping = {
            "light": {1: "低亮", 2: "关闭", 3: "中亮", 4: "高亮", 5: "呼吸", 6: "流水"},
            "fan": {7: "低速", 8: "关闭", 9: "中速", 10: "高速"},
            "heater": {15: "低温", 16: "关闭", 17: "中温", 18: "高温"},
        }
        return mapping.get(device, {}).get(value, "未知")

    def _update_status(self, light: str, fan: str, heater: str) -> None:
        """更新状态显示"""
        if self.status_table:
            self.status_table.data.clear()
            self.status_table.data.append(
                {"light": light, "fan": fan, "heater": heater}
            )

    def is_esp_device(self, mac: str) -> bool:
        """验证MAC地址"""
        cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
        return cleaned[:6] in self.esp_ouis

    def connect_bluetooth(self, widget: toga.Widget) -> None:
        """连接设备"""

        async def start_connect() -> None:
            if not self.device_table or not self.device_table.selection:
                await self.main_window.dialog(
                    toga.ErrorDialog("错误", "请先选择要连接的设备")
                )
                return

            address = self.device_table.selection.mac
            try:
                if await self.connect_to_device(address):
                    await self.main_window.dialog(
                        toga.InfoDialog("连接状态", "连接成功")
                    )
                else:
                    await self.main_window.dialog(toga.ErrorDialog("错误", "连接失败"))
            except Exception as e:
                await self.main_window.dialog(
                    toga.ErrorDialog("错误", f"连接异常: {str(e)}")
                )

        self.event_loop.create_task(start_connect())

    def disconnect_bluetooth(self, widget: toga.Widget) -> None:
        """断开连接"""

        async def start_disconnect() -> None:
            if self.client and self.client.is_connected:
                try:
                    await self.client.disconnect()
                    await self.main_window.dialog(
                        toga.InfoDialog("连接状态", "已断开连接")
                    )
                    self._update_status("-", "-", "-")
                except BleakError as e:
                    await self.main_window.dialog(
                        toga.ErrorDialog("错误", f"断开失败: {e}")
                    )
            else:
                await self.main_window.dialog(
                    toga.InfoDialog("提示", "当前没有已连接的设备")
                )

        self.event_loop.create_task(start_disconnect())


def main() -> BluetoothClient:
    """应用入口"""
    return BluetoothClient()
