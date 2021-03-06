'''
James Lin
jl3782
Server.py -- CSEE 4119 Programming Assignment 1
'''

import socket
import signal
import os
import threading
import time
import sys
from multiprocessing import Lock


RECV_SIZE = 1024
TIMEOUT = 45
LOCKOUT = 60
PORT = 0
HOST = ''
user_list = []
lock = Lock()
user_lock = 0

# class for users on the client side
class User:
    'Common class for all users in this chat program'

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.active = False
        self.logged_in = False
        self.port = 0
        self.ip = ''
        self.mailbox = []
        self.blocked_me = {}
        self.private_peer = ''
        self.locked_out = False

    def __str__(self):
        return self.username

# find in user by username
def find_user(username):
    global user_list
    for u in user_list:
        if u.username == username:
            return u
    return None

# multithread safe addition of user
def thread_add_user(user):
    global lock
    lock.acquire()
    try:
        user.logged_in = True
    finally:
        lock.release()

# multithread safe removal of user
def thread_remove_user(user):
    global lock
    lock.acquire()
    try:
        user.logged_in = False
        user.port = 0
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

# multithread safe update of user port and ip
def thread_add_user_port_ip(user, port, ip):
    global lock
    lock.acquire()
    try:
        user.port = int(port)
        user.ip = ip
    finally:
        lock.release()

# multithread safe update of user blocked list
def thread_add_blocking_user(user, blocking_user):
    global lock
    lock.acquire()
    try:
        user.blocked_me[blocking_user] = 1
    finally:
        lock.release()

# multithread safe removal of user blocked list
def thread_remove_blocking_user(user, blocking_user):
    global lock
    lock.acquire()
    try:
        del user.blocked_me[blocking_user]
    finally:
        lock.release()

# multithread safe addition of user peer
def thread_add_private_peer(user, peer):
    global lock
    lock.acquire()
    try:
        user.private_peer = peer
    finally:
        lock.release()

# multithread safe lock out of user
def thread_lock_out_user(user):
    global lock
    lock.acquire()
    try:
        user.locked_out = True
    finally:
        lock.release()

# multithread safe unlock of user
def thread_unlock_out_user(user):
    global lock
    lock.acquire()
    try:
        user.locked_out = False
    finally:
        lock.release()

# multithread safe addition to mailbox
def thread_add_to_mailbox(user, message):
    global lock
    lock.acquire()
    try:
        user.mailbox.append(message)
    finally:
        lock.release()

# multithread safe clearing of mailbox
def thread_clear_mailbox(user):
    global lock
    lock.acquire()
    try:
        user.mailbox = []
    finally:
        lock.release()

# multithread safe check of all the live users
def thread_check_pulse():
    global lock
    global user_list
    lock.acquire()
    try:
        for user in user_list:
            if user.logged_in == True and user.active == False:
                user.logged_in = False
                broadcast_message(user.username + ' logged out', user.username,
                    False)
            user.active = False
    finally:
        lock.release()

    # launch next pulse thread after TIMEOUT seconds
    time.sleep(TIMEOUT)
    check = threading.Thread(target=thread_check_pulse)
    check.daemon = True
    check.start()
    
    return(0)

# return string with pretty printed online users
def get_online_users(current_user):
    global user_list
    username_list = []

    for user in user_list:
        # do not include offline users and current user
        if user.logged_in == True and user is not current_user:
            # do not allow blocked users to see
            try:
                current_user.blocked_me[user.username]
                continue
            except Exception:
                username_list.append(user.username)

    return '\n'.join(username_list)

# send messages out to all online clients
def broadcast_message(message, sender, is_login):
    global user_list

    send_user = find_user(sender)
    for user in user_list:
        # presence broadcasts and other broadcasts have
        # different requirements as far as blocking goes
        if is_login:
            try:
                user.blocked_me[send_user.username]
                continue
            except Exception:
                if user.logged_in == True and user.username != sender:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        sock.connect((user.ip, user.port))
                        delay_send(sock, 'BCST', message)
                    except Exception:
                        print 'client connection closed'
                    sock.close()
        else:
            try:
                send_user.blocked_me[user.username]
                continue
            except Exception:
                if user.logged_in == True and user.username != sender:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        sock.connect((user.ip, user.port))
                        delay_send(sock, 'BCST', message)
                    except Exception:
                        print 'client connection closed'
                    sock.close()

# send message through the server to a specific client
def send_message(message, sender, receiver, code):

    rec_user = find_user(receiver)
    if rec_user == None or receiver == sender:
        ret_user = find_user(sender)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((ret_user.ip, ret_user.port))
            delay_send(sock, code, receiver + ' is not a valid user.')
        except Exception:
            # guaranteed delivery, will at least go to mailbox
            thread_add_to_mailbox(ret_user, message)
        sock.close()
    elif rec_user.logged_in == True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((rec_user.ip, rec_user.port))
            delay_send(sock, code, message)
        except Exception:
            # guaranteed delivery, will at least go to mailbox
            thread_add_to_mailbox(rec_user, message)
        sock.close()
    else:
        thread_add_to_mailbox(rec_user, message)

# send with a slight delay, fixed some timing issues I was having
def delay_send(connection, code, message):    
    try:
        connection.sendall(code)
        time.sleep(.1)
        connection.sendall(message)
    except Exception:
        print 'connection broken'

# check if this port is free, avoid race condition
def check_port_free(port_number):
    global user_list
    for user in user_list:
        if user.port == port_number:
            return False
    return True

# timeout function to be called by timeout thread
def lock_out_timeout(user):
    global LOCKOUT
    time.sleep(LOCKOUT)
    thread_unlock_out_user(user)
    return 0

# serve the connections
def serve_client(connection):

    global user_list

    greeting = connection.recv(RECV_SIZE)

    '''
    PTCK - port check, see if a port is free
    HELO - hello, initial greeting to get ready
    USER - username, time to get username info from client
    AUTH - authentication, getting password and checking if valid
    LIVE - heartbeat, checking to see if the client is still online_users
    CMND - command, numerous commands that are outlined below
    '''
    if greeting == 'PTCK':
        port_to_check = int(connection.recv(RECV_SIZE))
        port_free = check_port_free(port_to_check)
        if port_free:
            delay_send(connection, 'GDPT', '')
        else:
            delay_send(connection, 'BDPT', '')
    elif greeting == 'HELO':

        connection.recv(RECV_SIZE)
        delay_send(connection, 'USER', 'Username: ')
    elif greeting == 'USER':
        try:
            info = connection.recv(RECV_SIZE).split()
        except Exception:
            print 'connection broke'

        username = info[0]
        port = info[1]
        ip = info[2]

        # check to see if it's a valid username
        user = find_user(username)
        if user == None:
            try:
                delay_send(connection, 'FAIL', 'User not found. Try again')
            except Exception:
                print 'client connection closed'
        elif user.locked_out == True:
            delay_send(connection, 'FAIL', 
                'Your account is still locked out\n')
        else:
            thread_add_user(user)
            thread_add_user_port_ip(user, port, ip)
            delay_send(connection, 'PASS', 'Password: ') 
    elif greeting == 'AUTH':
        try:
            info = connection.recv(RECV_SIZE).split()
        except Exception:
            print 'connection broke'
        username = info[0]
        password = info[1]
        try_num = int(info[2])
        user = find_user(username)

        if try_num == 3 and password != user.password:
            # launch timeout thread
            thread_lock_out_user(user)
            t = threading.Thread(target=lock_out_timeout, args=(user,))
            t.daemon = True
            t.start()

            # send sad message
            delay_send(connection, 'FAIL', 'Due to multiple login failures, ' + 
                                   'your account has been blocked. Please ' +
                                   'try again after ' + str(LOCKOUT) + 
                                   ' seconds.')
        elif password != user.password:
            delay_send(connection, 'DENY', 'Invalid Password. ' + 
                                           'Please try again\n>Password: ')
        else:
            if user.logged_in == True:
                send_message('Another computer has logged in with your ' + 
                    'username and password.', '', username, 'LOGO')

            delay_send(connection, 'SUCC', 
                '>Welcome to simple chat server!')
            time.sleep(.1)

            # check mail
            if not user.mailbox:
                mail = '>No offline messages'
            else:
                mail = '\n'.join(user.mailbox)
                thread_clear_mailbox(user)

            delay_send(connection, username,
                '>Offline Messages:\n' + mail)
            broadcast_message(username + ' logged in', username, True)
    elif greeting == 'LIVE':

        username = connection.recv(RECV_SIZE)
        print 'LIVE: ' + username
        user = find_user(username)

        if user == None:
            print 'user broke off'
        elif user.logged_in == False:
            print 'user died, no heartbeat'
        else:
            thread_update_live_user(user)
            delay_send(connection, 'LIVE', 'Still living')
    elif greeting == 'CMND':

        user_input = connection.recv(RECV_SIZE)
        username = connection.recv(RECV_SIZE)
        user = find_user(username)
        input_array = user_input.split()

        '''
        logout - user.logged_in is marked as False
        online - user queries database for online users
        broadcast - broadcasts message to all online clients
        message - messages specific client, online or offline
        getaddress - gets IP and port info for P2P
        consent - gives client access to P2P information
        block - blacklists a given user
        unblock - removes given user from blacklist
        '''
        if user == None:
            print 'user broke off'
        elif user_input == '\n':
            print 'pressed enter'
        elif user_input == 'logout':

            thread_remove_user(user)
            delay_send(connection, 'LOGO', 'logout')
            broadcast_message(username + ' logged out', username, True)
        elif user_input == 'online':

            online_users = get_online_users(user)
            delay_send(connection, 'ONLN', online_users)
        elif input_array[0] == 'broadcast':

            delay_send(connection, 'BCST', '')
            broadcast_message(username + ': ' + user_input[len('broadcast '):], 
                username, False)
        elif input_array[0] == 'message' and len(input_array) > 1:

            delay_send(connection, 'MESG', '')
            receiver = input_array[1]

            # make sure to check for blocking
            try:
                user.blocked_me[receiver]
                send_message('You are blocked by ' + receiver, '', 
                    username, 'MESG')
            except Exception:
                message = user_input[(len('message ') + len(receiver) + 1):]
                send_message(username + ': ' + message, username, receiver, 
                    'MESG')
        elif input_array[0] == 'getaddress' and len(input_array) == 2:

            contact = input_array[1]
            contact_user = find_user(contact)

            # check to make sure user is not yourself
            if contact_user == None:
                delay_send(connection, 'NGET', 
                    contact + ' is not a valid user.')
            elif(len(input_array) == 2 and username != contact
                and contact_user.logged_in):
                try:
                    user.blocked_me[contact]
                    delay_send(connection, 'NGET', 'Blocked by ' + contact)
                except Exception:
                    thread_add_private_peer(user, contact)
                    send_message(username + ' is requesting a private chat. ' + 
                        'To share your IP and port with them, reply saying ' +
                        '\'consent '+ username +'\'', username, contact, 'RQST')
            else:
                delay_send(connection, 'NGET', 'Invalid request')
        elif input_array[0] == 'consent' and len(input_array) == 2:

            contact = input_array[1]
            contact_user = find_user(contact)

            if contact_user == None:
                delay_send(connection, 'NGET', 
                    contact + ' is not a valid user.')
            elif len(input_array) == 2 and username != contact:
                peer = find_user(contact)
                if username == peer.private_peer:
                    send_message(str(user.port) + ' ' + user.ip +  ' ' + 
                        username, username, contact, 'GETA')
                else:
                    send_message(contact + ' has not requested a P2P chat ' +
                        'with you. Use the getaddress command to start one',
                        contact, username, 'NGET')
        elif input_array[0] == 'block' and len(input_array) == 2:

            to_block = input_array[1]
            block_user = find_user(to_block)

            if block_user == None:
                delay_send(connection, 'NGET', 
                    to_block + ' is not a valid user.')   
            elif len(input_array) == 2 and username != to_block:
                thread_add_blocking_user(find_user(to_block), username)
                delay_send(connection, 'BLOK', 'User ' + to_block + 
                    ' has been blocked')
            else:
                delay_send(connection, 'NBLK', 'Unable to block user')
        elif input_array[0] == 'unblock' and len(input_array) == 2:

            to_unblock = input_array[1]
            unblock_user = find_user(to_unblock)

            if unblock_user == None:
                delay_send(connection, 'NGET', 
                    to_unblock + ' is not a valid user.')  
            elif len(input_array) == 2 and username != to_unblock:
                thread_remove_blocking_user(find_user(to_unblock), username)
                delay_send(connection, 'UBLK', 'User ' + to_unblock +
                    ' is unblocked')
            else:
                delay_send(connection, 'NUBK', 'Unable to unblock user')
        else:
            delay_send(connection, 'RECV', 'Invalid Command: ' + user_input)

    connection.close()
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

    # build all the users
    file_obj = open('credentials.txt', 'r')
    next_line = file_obj.readline()
    while next_line != '':
        line = str.split(next_line, '\n')
        line = str.split(line[0], ' ')
        user_list.append(User(line[0], line[1]))
        next_line = file_obj.readline()
    
    # launch the pulse checking daemon
    check = threading.Thread(target=thread_check_pulse)
    check.daemon = True
    check.start()

    # continuously running thread manager
    while True:

        conn, addr = s.accept()

        print 'Connected by ', addr
        t = threading.Thread(target=serve_client, args=(conn,))
        t.start()

# ^C terminate gracefully
def ctrl_c_handler(signum, frame):
    exit(0)

# kick off signal handlers and the main thread
def main():
    signal.signal(signal.SIGINT, ctrl_c_handler)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    main_thread()

if __name__ == '__main__': 
    main()