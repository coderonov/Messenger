import socket
import threading
import json
import os
import time
import datetime
import hashlib
import secrets

HOST = 'YOUR_LOCAL_IP'
PORT = 5555
USERS_FILE = 'users.json'
SALT_FILE = 'server.salt'

class Server:
    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind((HOST, PORT))
        self.server.listen()
        self.users = {}
        self.active_chats = {}
        self.online_users = {}
        self.load_salt()
        self.load_users()

    def log_event(self, event_type, address, details):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{event_type}] IP: {address[0]}:{address[1]}, Details: {details}")

    def load_salt(self):
        if os.path.exists(SALT_FILE):
            with open(SALT_FILE, 'rb') as f:
                self.salt = f.read()
        else:
            self.salt = secrets.token_bytes(32)
            with open(SALT_FILE, 'wb') as f:
                f.write(self.salt)

    def hash_password(self, password):
        return hashlib.pbkdf2_hmac('sha256', password.encode(), self.salt, 100000).hex()

    def load_users(self):
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, 'r') as f:
                    self.users = json.load(f)
            except:
                self.users = {}
        else:
            self.users = {}

    def save_users(self):
        with open(USERS_FILE, 'w') as f:
            json.dump(self.users, f)

    def send_contacts(self, username, client):
        contacts = []
        if username in self.users:
            for contact in self.users[username].get('contacts', []):
                if contact in self.users:
                    status = 'ONLINE' if contact in self.online_users else 'OFFLINE'
                    contacts.append({
                        'username': contact,
                        'display_name': self.users[contact]['display_name'],
                        'status': status
                    })
        client.send(f'CONTACTS:{json.dumps(contacts)}'.encode('utf-8'))

    def handle_client(self, client, address):
        current_user = None
        self.log_event("CONNECT", address, "Client connected")

        try:
            while True:
                data = client.recv(1024).decode('utf-8')
                if not data:
                    break

                self.log_event("RECEIVE", address, data)
                parts = data.split(':', 1)
                command = parts[0]

                if command == 'REGISTER':
                    if len(parts) < 2:
                        client.send('ERROR:Invalid command format'.encode('utf-8'))
                        continue

                    credentials = parts[1].split(':', 2)
                    if len(credentials) < 3:
                        client.send('ERROR:Invalid data format'.encode('utf-8'))
                        continue

                    username, password, display_name = credentials
                    if username in self.users:
                        client.send('ERROR:Username already exists'.encode('utf-8'))
                    else:
                        hashed_pw = self.hash_password(password)
                        self.users[username] = {
                            'password': hashed_pw,
                            'display_name': display_name,
                            'contacts': []
                        }
                        self.save_users()
                        client.send('SUCCESS:Registered successfully'.encode('utf-8'))
                        self.log_event("REGISTER", address, f"New user: {username}")

                elif command == 'LOGIN':
                    if len(parts) < 2:
                        client.send('ERROR:Invalid command format'.encode('utf-8'))
                        continue

                    credentials = parts[1].split(':', 1)
                    if len(credentials) < 2:
                        client.send('ERROR:Invalid data format'.encode('utf-8'))
                        continue

                    username, password = credentials
                    user = self.users.get(username)
                    hashed_pw = self.hash_password(password)
                    if user and user['password'] == hashed_pw:
                        current_user = username
                        self.online_users[username] = client
                        client.send(f'SUCCESS:Logged in:{user["display_name"]}'.encode('utf-8'))
                        self.log_event("LOGIN", address, f"User: {username}")
                        self.send_contacts(username, client)
                    else:
                        client.send('ERROR:Invalid credentials'.encode('utf-8'))

                elif command == 'FIND':
                    if len(parts) < 2:
                        client.send('ERROR:Invalid command format'.encode('utf-8'))
                        continue

                    target = parts[1]
                    if target in self.users:
                        status = 'ONLINE' if target in self.online_users else 'OFFLINE'
                        client.send(f'FOUND:{self.users[target]["display_name"]}:{status}'.encode('utf-8'))
                        self.log_event("FIND", address, f"Search: {target} -> Found")
                    else:
                        client.send('NOT_FOUND:User not found'.encode('utf-8'))

                elif command == 'INVITE':
                    if len(parts) < 2:
                        client.send('ERROR:Invalid command format'.encode('utf-8'))
                        continue

                    target_user = parts[1]
                    if target_user in self.online_users:
                        target_client = self.online_users[target_user]
                        target_client.send(f'INVITE:{current_user}:{self.users[current_user]["display_name"]}'.encode('utf-8'))
                        client.send('INVITE_SENT:Request sent'.encode('utf-8'))
                        self.log_event("INVITE", address, f"From {current_user} to {target_user}")
                    else:
                        client.send('ERROR:User offline'.encode('utf-8'))

                elif command == 'RESPONSE':
                    if len(parts) < 2:
                        client.send('ERROR:Invalid command format'.encode('utf-8'))
                        continue

                    response_data = parts[1].split(':', 1)
                    if len(response_data) < 2:
                        client.send('ERROR:Invalid response format'.encode('utf-8'))
                        continue

                    response, sender = response_data
                    self.log_event("RESPONSE", address, f"From {current_user} to {sender}: {response}")

                    if response == 'ACCEPT':
                        if sender in self.online_users:
                            self.active_chats[sender] = current_user
                            self.active_chats[current_user] = sender

                            self.online_users[sender].send(f'CHAT_START:{self.users[current_user]["display_name"]}'.encode('utf-8'))
                            client.send(f'CHAT_START:{self.users[sender]["display_name"]}'.encode('utf-8'))
                            self.log_event("CHAT_START", address, f"Between {current_user} and {sender}")
                        else:
                            client.send('ERROR:User offline'.encode('utf-8'))
                    else:
                        if sender in self.online_users:
                            self.online_users[sender].send('REJECTED:Chat request rejected'.encode('utf-8'))

                elif command == 'MESSAGE':
                    if len(parts) < 2:
                        continue

                    if current_user in self.active_chats:
                        target = self.active_chats[current_user]
                        if target in self.online_users:
                            msg = f'MESSAGE:{self.users[current_user]["display_name"]}:{parts[1]}'
                            self.online_users[target].send(msg.encode('utf-8'))
                            self.log_event("MESSAGE", address, f"From {current_user} to {target}")

                elif command == 'EXIT':
                    self.log_event("EXIT", address, f"User: {current_user}")
                    break

                elif command == 'ADD_CONTACT':
                    if len(parts) < 2:
                        client.send('ERROR:Invalid command format'.encode('utf-8'))
                        continue

                    contact_user = parts[1]
                    if contact_user not in self.users:
                        client.send('ERROR:User not found'.encode('utf-8'))
                        continue

                    if current_user not in self.users:
                        client.send('ERROR:Invalid user'.encode('utf-8'))
                        continue

                    if contact_user not in self.users[current_user]['contacts']:
                        self.users[current_user]['contacts'].append(contact_user)
                        self.save_users()
                        self.send_contacts(current_user, client)
                        client.send('SUCCESS:Contact added'.encode('utf-8'))
                    else:
                        client.send('SUCCESS:Contact already exists'.encode('utf-8'))

                elif command == 'REMOVE_CONTACT':
                    if len(parts) < 2:
                        client.send('ERROR:Invalid command format'.encode('utf-8'))
                        continue

                    contact_user = parts[1]
                    if current_user in self.users:
                        if contact_user in self.users[current_user]['contacts']:
                            self.users[current_user]['contacts'].remove(contact_user)
                            self.save_users()
                            self.send_contacts(current_user, client)
                            client.send('SUCCESS:Contact removed'.encode('utf-8'))
                        else:
                            client.send('ERROR:Contact not found'.encode('utf-8'))

                elif command == 'GET_CONTACTS':
                    if current_user:
                        self.send_contacts(current_user, client)

                elif command == 'CHANGE_PASSWORD':
                    if len(parts) < 2:
                        client.send('ERROR:Invalid command format'.encode('utf-8'))
                        continue

                    passwords = parts[1].split(':', 2)
                    if len(passwords) < 3:
                        client.send('ERROR:Invalid data format'.encode('utf-8'))
                        continue

                    old_password, new_password, confirm_password = passwords
                    if new_password != confirm_password:
                        client.send('ERROR:New passwords do not match'.encode('utf-8'))
                        continue

                    user = self.users.get(current_user)
                    hashed_old = self.hash_password(old_password)
                    if user and user['password'] == hashed_old:
                        hashed_new = self.hash_password(new_password)
                        user['password'] = hashed_new
                        self.save_users()
                        client.send('SUCCESS:Password changed'.encode('utf-8'))
                    else:
                        client.send('ERROR:Invalid old password'.encode('utf-8'))

                elif command == 'PING':
                    client.send('PONG:'.encode('utf-8'))

        except Exception as e:
            self.log_event("ERROR", address, f"Exception: {str(e)}")
        finally:
            if current_user:
                if current_user in self.online_users:
                    del self.online_users[current_user]
                if current_user in self.active_chats:
                    target = self.active_chats[current_user]
                    if target in self.online_users:
                        self.online_users[target].send('CHAT_END:User disconnected'.encode('utf-8'))
                    if target in self.active_chats:
                        del self.active_chats[target]
                    del self.active_chats[current_user]
            client.close()
            self.log_event("DISCONNECT", address, f"User: {current_user}")

    def start(self):
        print(f"╔{'═' * 60}╗")
        print(f"║{'СЕРВЕР ЗАПУЩЕН':^60}║")
        print(f"║{'═' * 60}║")
        print(f"║ Публичный IP: {HOST:<45}║")
        print(f"║ Порт: {PORT:<53}║")
        print(f"╚{'═' * 60}╝\n")
        print("Ожидание подключений...")
        while True:
            client, address = self.server.accept()
            self.log_event("CONNECT", address, "New connection")
            thread = threading.Thread(target=self.handle_client, args=(client, address))
            thread.start()

if __name__ == "__main__":
    server = Server()
    server.start()