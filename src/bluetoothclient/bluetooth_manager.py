import asyncio
import logging
import json
from importlib.resources import files
from bleak import BleakClient, BleakError, BleakGATTCharacteristic, BleakScanner
from re import sub


class BluetoothManager:
    def __init__(self, service_uuid, char_uuid, target_name, esp_ouis, status_callback=None):
        super().__init__()
        self.service_uuid = service_uuid
        self.char_uuid = char_uuid
        self.logger = logging.getLogger(self.__class__.__name__)
        self.client = None
        self.target_name = target_name
        self.esp_ouis = esp_ouis
        self.event_loop = asyncio.get_event_loop()
        self.status_callback = status_callback

    async def scan_devices(self):
        self.logger.info("开始扫描蓝牙设备...")
        try:
            devices = await BleakScanner.discover()
            matched = [
                {"name": d.name, "mac": d.address}
                for d in devices
                if d.name
                and (self.target_name in d.name or self.is_esp_device(d.address))
            ]
            return matched
        except BleakError as e:
            self.logger.error(f"扫描失败: {str(e)}")
            return []

    async def connect_to_device(self, address):
        try:
            self.client = BleakClient(address)
            await self.client.connect()

            # 验证服务
            target_service = self.service_uuid.replace("-", "").lower()
            target_char = self.char_uuid.replace("-", "").lower()

            for service in self.client.services:
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

    async def send_command(self, value):
        if not self.client or not self.client.is_connected:
            return False

        try:
            await self.client.write_gatt_char(self.char_uuid, bytes([value]))
            self.logger.info(f"成功发送指令: {value}")
            return True
        except BleakError as e:
            self.logger.error(f"发送失败: {str(e)}")
            return False

    def notification_handler(self, _: BleakGATTCharacteristic, data: bytearray):
        if len(data) == 3:
            status = {
                "light": self._parse_status(data[0], "light"),
                "fan": self._parse_status(data[1], "fan"),
                "heater": self._parse_status(data[2], "heater"),
            }
            if self.status_callback:
                self.status_callback(status)
            return status

    def _parse_status(self, value: int, device: str) -> str:
        resource_path = files("bluetoothclient.resources") / "device.json"
        with resource_path.open(encoding='utf-8') as file:
            device_data = json.load(file)

        # 构建 mapping
        mapping = {}
        for item in device_data:
            device_name = item["device_name"]
            mapping[device_name.lower()] = {button["command"]: button["option"] for button in item["buttons"]}

        # 修正 device 名称映射
        device_mapping = {
            "light": "灯光",
            "fan": "风扇",
            "heater": "电热器"
        }
        proper_device_name = device_mapping.get(device, device)

        return mapping.get(proper_device_name, {}).get(value, "未知")

    def is_esp_device(self, mac: str) -> bool:
        cleaned = sub(r"[^0-9A-Fa-f]", "", mac).upper()
        return cleaned[:6] in self.esp_ouis

    async def disconnect(self):
        if self.client:
            try:
                await self.client.disconnect()
                await self.client.__aexit__(None, None, None)
                self.client = None
                return True
            except BleakError as e:
                self.logger.error(f"断开失败: {str(e)}")
                return False
        return True