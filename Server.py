import Queue
import socket
import signal
import os
import threading
import time
import sys
from multiprocessing import Lock


RECV_SIZE = 1024
TIMEOUT = 15
user_list = []
lock = Lock()
user_lock = 0
PORT = 0
HOST = ''

# class for users on the client side
class User:
    'Common class for all users in this chat program'

    def __init__(self, username, password, active, loggedin):
        self.username = username
        self.password = password
        self.active = active
        self.loggedin = loggedin
        self.port = 0
        self.mailbox = []

    def __str__(self):
        return self.username

# find in user by username
def find_user(username):
    for u in user_list:
        if u.username == username:
            return u
    return None

# multithread safe addition of user
def thread_add_user(user):
    global lock
    lock.acquire()
    try:
        user.loggedin = True
    finally:
        lock.release()

# multithread safe removal of user
def thread_remove_user(user):
    global lock
    lock.acquire()
    try:
        user.loggedin = False
    finally:
        lock.release()

# multithread safe heartbeat function
def thread_update_live_user(user):
    global lock
    lock.acquire()
    try:
        user.active = True
    finally:
        lock.release()

# multithread safe update of user port
def thread_add_user_port(user, port):
    global lock
    lock.acquire()
    try:
        user.port = int(port)
    finally:
        lock.release()

# multithread safe check of all the live users
def thread_check_pulse():
    global lock
    global user_list
    lock.acquire()
    try:
        for user in user_list:
            if user.loggedin == True and user.active == False:
                user.loggedin = False
                broadcast_message(user.username + ' logged out', user.username)
            user.active = False
    finally:
        lock.release()

    time.sleep(TIMEOUT)
    check = threading.Thread(target=thread_check_pulse)
    check.daemon = True
    check.start()
    
    return(0)

def thread_add_to_mailbox(user, message):
    global lock
    lock.acquire()
    try:
        user.mailbox.append(message)
    finally:
        lock.release()

def thread_clear_mailbox(user):
    global lock
    lock.acquire()
    try:
        user.mailbox = []
    finally:
        lock.release()

# return string with pretty printed online users
def get_online_users():
    global user_list
    username_list = []

    for user in user_list:
        if user.loggedin == True:
            username_list.append(user.username)

    return '\n'.join(username_list)

def broadcast_message(message, sender):
    global user_list
    global HOST

    for user in user_list:
        if user.loggedin == True and user.username != sender:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.connect((HOST, user.port))
                sock.sendall(message)
            except Exception:
                print 'client connection closed'
            sock.close()

def send_message(message, sender, receiver):
    global HOST

    rec_user = find_user(receiver)
    if rec_user.loggedin == True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((HOST, rec_user.port))
            sock.sendall(message)
        except Exception:
            print 'client connection closed'
        sock.close()
    else:
        thread_add_to_mailbox(rec_user, message)


# serve the connections
def serve_client(connection):
    print 'fresh thread launched'

    global user_list
    greeting = connection.recv(RECV_SIZE)
    print greeting
    # logging in for the first time
    if greeting == 'HELO':

        port = connection.recv(RECV_SIZE)
        connection.sendall('USER')
        # is this necessary???
        time.sleep(.1)
        connection.sendall('Username: ')
        username = connection.recv(RECV_SIZE)

        # check to see if it's a valid username
        user = find_user(username)
        if user == None:
            try:
                connection.sendall('FAIL')
                time.sleep(.1)
                connection.sendall('User not found. Try again')
            except Exception:
                print 'client connection closed'
        else:
            # otherwise, it passes the first test
            verified = authenticate(connection, user, username)

            if verified:

                if user.loggedin == False:
                    thread_add_user(user)
                    thread_add_user_port(user, port)
                    connection.sendall('SUCC')
                    time.sleep(.1)
                    connection.sendall('>Welcome to simple chat server!')
                    time.sleep(.1)
                    connection.sendall(username)
                    time.sleep(.1)

                    # check mail
                    if not user.mailbox:
                        mail = '>No offline messages'
                    else:
                        mail = '\n'.join(user.mailbox)
                        thread_clear_mailbox(user)

                    connection.sendall('>Offline Messages:\n' + mail)
                    broadcast_message(username + ' logged in', username)
                else:
                    connection.sendall('FAIL')
                    time.sleep(.1)
                    connection.sendall('Your account is already logged in\n')
    elif greeting == 'LIVE':

        username = connection.recv(RECV_SIZE)
        print 'heartbeat received from ' + username
        user = find_user(username)

        if user == None:
            print 'user broke off'
        elif user.loggedin == False:
            print 'user died, no heartbeat'
        else:
            thread_update_live_user(user)
            connection.sendall('LIVE')
            time.sleep(.1)
            connection.sendall('Still living')
    elif greeting == 'CMND':

        user_input = connection.recv(RECV_SIZE)
        username = connection.recv(RECV_SIZE)
        user = find_user(username)
        input_array = user_input.split()

        if user == None:
            print 'user broke off'
        elif user_input == 'logout':
            thread_remove_user(user)
            connection.sendall('LOGO')
            time.sleep(.1)
            connection.sendall('logout')
            broadcast_message(user.username + ' logged out', user.username)
        elif user_input == 'online':
            connection.sendall('ONLN')
            time.sleep(.1)
            online_users = get_online_users()
            connection.sendall(online_users)
        elif input_array[0] == 'broadcast':
            sender = input_array.pop()
            input_array.remove(input_array[0])
            message = ' '.join(input_array)
            broadcast_message(sender + ': ' + message, sender)
        elif input_array[0] == 'message':
            sender = input_array.pop()
            receiver = input_array[1]
            input_array.remove(input_array[0])
            input_array.remove(input_array[0])
            message = ' '.join(input_array)
            send_message(sender + ': ' + message, sender, receiver)
        else:
            connection.sendall('RECV')
            time.sleep(.1)
            connection.sendall('server: ' + user_input)

    connection.close()
    print 'thread terminated'
    return(0)

# parent process which keeps accepting connections
def main_thread():
    
    global user_list
    global PORT
    global HOST

    if len(sys.argv) < 2:
        print 'usage: python Server.py <PORT NUMBER>'
        exit(1)

    HOST = ''
    PORT = int(sys.argv[1])
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    s.bind((HOST, PORT))
    s.listen(1)

    file_obj = open('credentials.txt', 'r')
    next_line = file_obj.readline()
    while next_line != '':
        line = str.split(next_line, '\n')
        line = str.split(line[0], ' ')
        user_list.append(User(line[0], line[1], False, False))
        next_line = file_obj.readline()
    
    check = threading.Thread(target=thread_check_pulse)
    check.daemon = True
    check.start()

    while True:

        conn, addr = s.accept()

        print 'Connected by ', addr
        t = threading.Thread(target=serve_client, args=(conn,))
        t.start()

# authenticate the user
def authenticate(connection, user, username):

    count = 0
    verified = False
    correct_pass = user.password
    connection.sendall('PASS')
    time.sleep(.1)
    connection.sendall('Password: ')
    
    while count < 3 and not verified:
        
        password = connection.recv(RECV_SIZE)

        if password == correct_pass:
            verified = True
        elif count == 2:
            connection.sendall('FAIL')
            time.sleep(.1)
            connection.sendall('Due to multiple login failures, your account ' +
                               'has been blocked. Please try again after ' +
                               'sometime.')
        else:
            connection.sendall('DENY')
            time.sleep(.1)
            connection.sendall('Invalid Password. ' + 
                               'Please try again\n>Password: ')
        count = count + 1

    return verified

def ctrl_c_handler(signum, frame):
    exit(0)

def main():
    signal.signal(signal.SIGINT, ctrl_c_handler)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    main_thread()

if __name__ == '__main__': main()