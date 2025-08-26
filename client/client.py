import socket
import threading
import sys
import time
import platform
import datetime
import json
import random
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import get_color_from_hex

Window.clearcolor = get_color_from_hex("#121212")
Window.size = (400, 600)

SERVER_IP = '95.165.142.216'
PORT = 5555

IS_ANDROID = False
try:
    from jnius import autoclass
    from android.runnable import run_on_ui_thread
    from android.permissions import request_permissions, Permission
    Toast = autoclass('android.widget.Toast')
    context = autoclass('org.kivy.android.PythonActivity').mActivity
    IS_ANDROID = True
except ImportError:
    pass

def show_toast(message):
    if IS_ANDROID:
        @run_on_ui_thread
        def toast():
            Toast.makeText(context, str(message), Toast.LENGTH_SHORT).show()
        toast()
    else:
        print(f"💬 [TOAST] {message}")

class Client:
    def __init__(self):
        self.client = None
        self.connected = False
        self.username = None
        self.display_name = None
        self.in_chat = False
        self.chat_partner = None
        self.receive_thread = None
        self.pending_invite = None
        self.chat_history = []
        self.last_ping = 0
        self.ping_time = 0
        self.start_time = time.time()
        self.status = "🟢 В сети"
        self.contacts = []
        self.password = None
        self.callbacks = []
        self.lock = threading.Lock()
        self.connect_to_server()
        self.start_receive_thread()
        self.start_ping_thread()

    def connect_to_server(self):
        try:
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.settimeout(10)
            self.client.connect((SERVER_IP, PORT))
            self.connected = True
            self.status = "🟢 В сети"
            return True
        except Exception as e:
            self.connected = False
            self.status = "🔴 Отключен"
            self.trigger_callback('show_error', f"Нет подключения: {str(e)}")
            return False

    def start_receive_thread(self):
        if self.receive_thread is None or not self.receive_thread.is_alive():
            self.receive_thread = threading.Thread(target=self.receive_messages, daemon=True)
            self.receive_thread.start()

    def start_ping_thread(self):
        def ping():
            while True:
                time.sleep(5)
                if not self.connected:
                    continue
                try:
                    self.last_ping = time.time()
                    self.send('PING:')
                except:
                    self.connected = False
                    self.status = "🔴 Отключен"
                    break
        thread = threading.Thread(target=ping, daemon=True)
        thread.start()

    def receive_messages(self):
        buffer = ""
        while True:
            if not self.connected:
                time.sleep(1)
                continue
            try:
                data = self.client.recv(1024).decode('utf-8', errors='ignore')
                if not data:
                    break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line:
                        self.handle_message(line)
            except Exception as e:
                self.connected = False
                self.trigger_callback('show_error', "Соединение потеряно")
                break

    def handle_message(self, message):
        if not message:
            return
        parts = message.split(':', 2)
        command = parts[0]

        if command == 'SUCCESS':
            if parts[1].startswith('Logged in'):
                self.display_name = parts[2] if len(parts) > 2 else self.username
                self.send('GET_CONTACTS:')
            self.trigger_callback('show_success', parts[1])

        elif command in ('ERROR', 'NOT_FOUND', 'REJECTED'):
            msg = parts[1] if len(parts) > 1 else "Ошибка"
            self.trigger_callback('show_error', msg)

        elif command == 'FOUND':
            user = parts[1] if len(parts) > 1 else "неизвестный"
            display = parts[2] if len(parts) > 2 else user
            self.trigger_callback('show_found', user, display)

        elif command == 'INVITE':
            if len(parts) >= 3:
                self.pending_invite = (parts[1], parts[2])
                self.trigger_callback('show_invite', parts[1], parts[2])

        elif command == 'CHAT_START':
            self.in_chat = True
            self.chat_partner = parts[1] if len(parts) > 1 else "Собеседник"
            self.chat_history = []
            self.trigger_callback('start_chat', self.chat_partner)

        elif command == 'CHAT_END':
            reason = parts[1] if len(parts) > 1 else "Чат завершён"
            self.in_chat = False
            self.trigger_callback('show_notification', reason)
            self.trigger_callback('show_chat_menu')

        elif command == 'MESSAGE':
            sender = parts[1] if len(parts) > 1 else "Аноним"
            text = parts[2] if len(parts) > 2 else ""
            self.add_message_to_history(sender, text)

        elif command == 'TYPING':
            self.trigger_callback('show_typing', True)
            Clock.schedule_once(lambda dt: self.trigger_callback('show_typing', False), 1.2)

        elif command == 'PONG':
            self.ping_time = int((time.time() - self.last_ping) * 1000)

        elif command == 'CONTACTS':
            raw_data = parts[1] if len(parts) > 1 else "[]"
            try:
                contacts = json.loads(raw_data)
                self.contacts = contacts
                self.trigger_callback('update_contacts', self.contacts)
            except Exception as e:
                self.trigger_callback('show_error', f"Контакты: ошибка ({str(e)})")

    def add_message_to_history(self, sender, text):
        timestamp = datetime.datetime.now().strftime("%H:%M")
        color = "#00aaff" if sender == self.display_name else "#ffffff"
        align = "right" if sender == self.display_name else "left"
        bubble_color = "#00aaff" if sender == self.display_name else "#2d2d2d"
        name = "Вы" if sender == self.display_name else sender
        msg_html = (
            f'[color={color}][b]{name}[/b] • {timestamp}[/color]\n'
            f'[ref={sender}]'
            f'[size=14][b][color=black]{text}[/color][/b][/size]'
            f'[/ref]\n'
        )
        with self.lock:
            self.chat_history.append((msg_html, align, bubble_color))
            self.chat_history = self.chat_history[-100:]
        self.trigger_callback('update_chat', self.chat_history)

    def trigger_callback(self, event, *args):
        def call(dt):
            for cb in self.callbacks:
                if cb['event'] == event:
                    try:
                        cb['func'](*args)
                    except Exception as e:
                        print(f"Callback error: {e}")
        Clock.schedule_once(call, 0)

    def send(self, msg):
        if self.connected:
            try:
                self.client.send((msg + '\n').encode('utf-8'))
            except Exception as e:
                self.connected = False
                self.trigger_callback('show_error', "Ошибка отправки")

    def register(self, username, password, display_name):
        if username and password:
            self.send(f'REGISTER:{username}:{password}:{display_name or username}')

    def login(self, username, password):
        self.username = username
        self.password = password
        if username and password:
            self.send(f'LOGIN:{username}:{password}')

    def send_message(self, text):
        if self.in_chat and text.strip():
            self.send(f'MESSAGE:{text}')

    def invite_user(self, target):
        if target:
            self.send(f'INVITE:{target}')

    def find_user(self, target):
        if target:
            self.send(f'FIND:{target}')

    def add_contact(self, username):
        if username:
            self.send(f'ADD_CONTACT:{username}')

    def remove_contact(self, username):
        if username:
            self.send(f'REMOVE_CONTACT:{username}')

    def respond_invite(self, response, username):
        if username:
            self.send(f'RESPONSE:{response}:{username}')

    def change_password(self, old, new, confirm):
        if new == confirm:
            self.send(f'CHANGE_PASSWORD:{old}:{new}:{confirm}')
        else:
            self.trigger_callback('show_error', "Пароли не совпадают")

    def logout(self):
        if self.connected:
            try:
                self.send('EXIT:')
            except:
                pass
        self.in_chat = False
        self.username = None
        self.display_name = None
        self.trigger_callback('show_main_menu')

class MessengerApp(App):
    def build(self):
        self.client = Client()
        self.layout = BoxLayout(orientation='vertical', padding=10, spacing=8)
        if IS_ANDROID:
            request_permissions([Permission.INTERNET, Permission.ACCESS_NETWORK_STATE])
        Clock.schedule_interval(self.update_status, 2)
        self.create_main_menu()
        return self.layout

    def update_status(self, dt):
        children = self.layout.children
        for child in children:
            if isinstance(child, Label) and "Статус:" in child.text:
                child.text = f"Статус: {self.client.status} | Пинг: {self.client.ping_time}ms"
                break

    def create_main_menu(self, *args):
        self.layout.clear_widgets()
        title = self.label("💬 Мессенджер PREMIUM", font_size=26, color="#00aaff", height=60)
        self.layout.add_widget(title)
        status = self.label(f"Статус: {self.client.status}", font_size=14, color="#ffff00")
        self.layout.add_widget(status)
        self.add_button("📝 Регистрация", self.show_register, bg="#0088ff")
        self.add_button("🔑 Вход", self.show_login, bg="#0088ff")
        self.add_button("⚙️ Настройки", self.show_settings, bg="#555555")
        self.add_button("🚪 Выход", lambda x: App.get_running_app().stop(), bg="#ff3333")
        self.client.callbacks = [cb for cb in self.client.callbacks if cb['event'] not in ('show_success', 'show_error', 'show_main_menu')]
        self.add_callback('show_success', self.show_success)
        self.add_callback('show_error', self.show_error)
        self.add_callback('show_main_menu', self.create_main_menu)

    def label(self, text, font_size=16, color="#ffffff", height=None):
        color = get_color_from_hex(color)
        lbl = Label(text=text, font_size=font_size, color=color, size_hint_y=None, height=height or 40)
        lbl.text_size = (Window.width - 20, None)
        lbl.halign = 'center'
        lbl.valign = 'middle'
        return lbl

    def add_button(self, text, func, bg="#333333", fg="#ffffff"):
        btn = Button(text=text, font_size=16, size_hint_y=None, height=50)
        btn.background_color = get_color_from_hex(bg)
        btn.color = get_color_from_hex(fg)
        btn.bind(on_press=func)
        self.layout.add_widget(btn)

    def add_callback(self, event, func):
        self.client.callbacks.append({'event': event, 'func': func})

    def show_register(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("🔐 РЕГИСТРАЦИЯ", font_size=20, color="#00aaff"))
        username = TextInput(hint_text="Логин", multiline=False, font_size=16, background_color=get_color_from_hex("#222222"))
        password = TextInput(hint_text="Пароль", password=True, multiline=False, font_size=16, background_color=get_color_from_hex("#222222"))
        display = TextInput(hint_text="Имя (опционально)", multiline=False, font_size=16, background_color=get_color_from_hex("#222222"))
        for w in [username, password, display]:
            self.layout.add_widget(w)
        self.add_button("✅ Зарегистрироваться", lambda x: self.do_register(username.text, password.text, display.text))
        self.add_button("⬅️ Назад", self.create_main_menu, bg="#555555")

    def do_register(self, username, password, display):
        if not username or not password:
            self.show_error("Логин и пароль обязательны")
            return
        self.client.register(username, password, display or username)

    def show_login(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("🔑 АВТОРИЗАЦИЯ", font_size=20, color="#00aaff"))
        username = TextInput(hint_text="Логин", multiline=False, font_size=16, background_color=get_color_from_hex("#222222"))
        password = TextInput(hint_text="Пароль", password=True, multiline=False, font_size=16, background_color=get_color_from_hex("#222222"))
        self.layout.add_widget(username)
        self.layout.add_widget(password)
        self.add_button("🔓 Войти", lambda x: self.do_login(username.text, password.text))
        self.add_button("⬅️ Назад", self.create_main_menu, bg="#555555")

    def do_login(self, username, password):
        if not username or not password:
            self.show_error("Введите логин и пароль")
            return
        self.client.login(username, password)

    def show_settings(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("⚙️ НАСТРОЙКИ", font_size=20, color="#00aaff"))
        self.add_button(f"🟢 Статус: {self.client.status}", self.change_status, bg="#555555")
        self.add_button("ℹ️ Информация", self.show_info, bg="#555555")
        self.add_button("⬅️ Назад", self.create_main_menu, bg="#ff3333")

    def change_status(self, *args):
        statuses = ["🟢 В сети", "⏱ Не беспокоить", "🟡 Невидимка"]
        idx = statuses.index(self.client.status) if self.client.status in statuses else 0
        self.client.status = statuses[(idx + 1) % 3]
        self.show_settings()

    def show_info(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("ℹ️ ИНФОРМАЦИЯ", font_size=20, color="#00aaff"))
        uptime = int(time.time() - self.client.start_time)
        info = f"📶 Пинг: {self.client.ping_time} мс\n⏱ В сети: {uptime} сек"
        self.layout.add_widget(self.label(info, font_size=14, color="#bbbbbb"))
        self.add_button("⬅️ Назад", self.show_settings, bg="#555555")

    def show_chat_menu(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label(f"🏠 Добро пожаловать, {self.client.display_name}", font_size=18, color="#00aaff"))
        self.layout.add_widget(self.label(f"Статус: {self.client.status} | Пинг: {self.client.ping_time}ms", font_size=13, color="#ffff00"))
        self.add_button("🔍 Найти пользователя", self.show_find_user, bg="#0088ff")
        self.add_button("👥 Мои контакты", self.show_contacts, bg="#0088ff")
        self.add_button("🔐 Настройки аккаунта", self.show_account_settings, bg="#555555")
        self.add_button("🚪 Выйти", lambda x: self.client.logout(), bg="#ff3333")
        if self.client.pending_invite:
            self.add_button("📨 Обработать запрос", self.handle_pending_invite, bg="#ff9500")

    def show_find_user(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("🔍 Поиск пользователя", font_size=18, color="#00aaff"))
        inp = TextInput(hint_text="Введите логин", multiline=False, background_color=get_color_from_hex("#222222"))
        self.layout.add_widget(inp)
        self.add_button("🔎 Найти", lambda x: self.client.find_user(inp.text))
        self.add_button("⬅️ Назад", self.show_chat_menu, bg="#555555")

    def show_contacts(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("👥 Контакты", font_size=18, color="#00aaff"))
        scroll = ScrollView()
        grid = GridLayout(cols=1, size_hint_y=None, spacing=5, padding=5)
        grid.bind(minimum_height=grid.setter('height'))
        for c in self.client.contacts:
            status = "🟢" if c.get('status') == 'ONLINE' else "🔴"
            name = c.get('display_name', c.get('username', 'Без имени'))
            btn_text = f"{status} {name} ({c['username']})"
            btn = Button(text=btn_text, size_hint_y=None, height=50, background_color=get_color_from_hex("#2a2a2a"))
            grid.add_widget(btn)
        scroll.add_widget(grid)
        self.layout.add_widget(scroll)
        self.add_button("➕ Добавить контакт", self.add_contact_screen, bg="#0088ff")
        self.add_button("⬅️ Назад", self.show_chat_menu, bg="#555555")

    def add_contact_screen(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("➕ Добавить контакт", font_size=18))
        inp = TextInput(hint_text="Логин пользователя", multiline=False, background_color=get_color_from_hex("#222222"))
        self.layout.add_widget(inp)
        self.add_button("📤 Отправить запрос", lambda x: self.client.add_contact(inp.text))
        self.add_button("⬅️ Назад", self.show_contacts, bg="#555555")

    def show_account_settings(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("🔐 Настройки аккаунта", font_size=18, color="#00aaff"))
        self.add_button("🔐 Сменить пароль", self.change_password_screen, bg="#555555")
        self.add_button("ℹ️ Информация", self.show_info, bg="#555555")
        self.add_button("⬅️ Назад", self.show_chat_menu, bg="#ff3333")

    def change_password_screen(self, *args):
        self.layout.clear_widgets()
        self.layout.add_widget(self.label("🔐 Смена пароля", font_size=18))
        old = TextInput(hint_text="Старый пароль", password=True, multiline=False, background_color=get_color_from_hex("#222222"))
        new = TextInput(hint_text="Новый пароль", password=True, multiline=False, background_color=get_color_from_hex("#222222"))
        confirm = TextInput(hint_text="Подтвердите", password=True, multiline=False, background_color=get_color_from_hex("#222222"))
        for w in [old, new, confirm]:
            self.layout.add_widget(w)
        self.add_button("✅ Сменить", lambda x: self.client.change_password(old.text, new.text, confirm.text))
        self.add_button("⬅️ Назад", self.show_account_settings, bg="#555555")

    def handle_pending_invite(self, *args):
        if not self.client.pending_invite:
            return
        username, display = self.client.pending_invite
        self.layout.clear_widgets()
        self.layout.add_widget(self.label(f"📨 Запрос от {display}", font_size=18))
        self.add_button("✅ Принять", lambda x: self.client.respond_invite("ACCEPT", username), bg="#00aa00")
        self.add_button("❌ Отклонить", lambda x: self.client.respond_invite("REJECT", username), bg="#ff3333")
        self.add_button("⬅️ Назад", self.show_chat_menu, bg="#555555")

    def start_chat_screen(self, partner):
        self.layout.clear_widgets()
        header = self.label(f"💬 Чат с {partner}", font_size=18, color="#00aaff", height=50)
        self.layout.add_widget(header)
        self.chat_output = Label(
            text="", size_hint_y=0.7, text_size=(Window.width - 30, None),
            valign='top', halign='left', padding=(10, 10)
        )
        self.chat_output.bind(size=self.chat_output.setter('text_size'))
        scroll = ScrollView(size_hint_y=0.7)
        scroll.add_widget(self.chat_output)
        self.layout.add_widget(scroll)
        self.message_input = TextInput(
            hint_text="Напишите сообщение...", size_hint_y=0.1,
            multiline=False, background_color=get_color_from_hex("#222222"),
            foreground_color=get_color_from_hex("#ffffff")
        )
        self.message_input.bind(on_text_validate=self.send_message)
        self.layout.add_widget(self.message_input)
        self.add_button("🚪 Выйти из чата", self.exit_chat, bg="#ff3333")
        self.add_callback('update_chat', self.update_chat_display)
        self.add_callback('show_typing', self.show_typing_indicator)

    def update_chat_display(self, history):
        content = ""
        for msg, align, color in history:
            bubble_style = f'background-color: {color}; padding: 10px; margin: 4px; border-radius: 12px; max-width: 70%'
            content += f'[b][align={align}][{bubble_style}]{msg}[/align][/b]\n'
        self.chat_output.text = content

    def show_typing_indicator(self, active):
        if active:
            self.chat_output.text += f"\n[italic][color=#aaaaaa]⏳ {self.client.chat_partner} печатает...[/color][/italic]"
        else:
            lines = self.chat_output.text.split('\n')
            self.chat_output.text = '\n'.join([l for l in lines if "печатает" not in l])

    def send_message(self, instance):
        text = instance.text.strip()
        if text:
            self.client.send_message(text)
            instance.text = ""
            self.client.send_typing()

    def exit_chat(self, *args):
        if self.client.in_chat:
            self.client.send("CHAT_END:")
            self.client.in_chat = False
        self.create_main_menu()

    def show_success(self, message):
        show_toast(f"✅ {message}")

    def show_error(self, message):
        show_toast(f"❌ {message}")

if __name__ == "__main__":
    MessengerApp().run()