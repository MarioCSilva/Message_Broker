import socket
import json
import selectors
import xml.etree.ElementTree as ET
import pickle

class Broker :
    def __init__(self):
        self.HOST=''
        self.PORT=8000
        self.sock = socket.socket()
        self.sock.bind((self.HOST, self.PORT))
        self.sock.listen(100)
        self.sel = selectors.DefaultSelector()
        self.usersdict={} #each user and its serialization mechanism
        self.topicmsg={} # each topic and as value : the messages published for that topic and its subtopics
        self.run()
    def accept(self, sock, mask):
        conn, addr = self.sock.accept()
        print('accepted', conn, 'from', addr)
        #after stablishing the connection with the Queue's socket the first message sended is the serialization mecanism of that queue
        nBytes=conn.recv(5)
        if nBytes:
            nBytes=int(nBytes.decode())
            data=conn.recv(nBytes)
            if data:
                if data.decode('utf-8')=='JSONQueue':
                    self.usersdict[conn]='JSON'
                elif data.decode('utf-8') == 'PickleQueue':
                    self.usersdict[conn] = 'PICKLE'
                elif data.decode('utf-8') == 'XMLQueue':
                    self.usersdict[conn] = 'XML'
        else:
            #if no data received close the connection                    
            print('closing', conn)
            self.sel.unregister(conn)
            conn.close()
        #conn.setblocking(False)
        self.sel.register(conn, selectors.EVENT_READ, self.read)
    def sendMsg(self, sock, method, topic, msg):
        #as we saved in our usersdict data structure every socket serial. mechanism we can now now how to encode each message
        if self.usersdict[sock]=='JSON':
            #encode in JSON
            sendmsg=self.encodeJSON(method,topic,msg)  
        elif self.usersdict[sock] == 'PICKLE':
            #encode in Pickle
            sendmsg=self.encodePICKLE(method,topic,msg)
        elif self.usersdict[sock] == 'XML':
            #and last in JSON
            sendmsg=self.encodeXML(method,topic,msg)
        #Before sending the message itself,send first the size of it with
        msgsize=str(len(sendmsg))
        msgsize="{:>5}".format(msgsize)
        msgsize=msgsize.encode('utf-8')
        sock.send(msgsize)
        #now we can send the message
        sock.send(sendmsg)

    def read(self, conn, mask):
        #receive rest of info from middleware
        nBytes=conn.recv(5)
        if nBytes:
            nBytes=int(nBytes.decode('utf-8'))
            data=conn.recv(nBytes)
            if data:
                if conn in self.usersdict:
                    #first check how to decode the message
                    if self.usersdict[conn] == 'JSON':
                        method,topic,msg=self.decodeJSON(data)
                    elif self.usersdict[conn] == 'PICKLE':
                        method,topic,msg=self.decodePICKLE(data)
                    elif self.usersdict[conn] == 'XML':
                        method,topic,msg=self.decodeXML(data)
                    #check the method associated with the message 
                    if method == 'PUBLISH':
                        self.readPubSub(conn,method,topic,msg)
                    elif method == 'SUBSCRIBE':
                        self.readPubSub(conn,method,topic)
                    elif method == 'CANCEL_SUB':
                        self.readCancelSub(conn,msg)
                    elif method == 'LIST':    
                        self.listTopics(True,conn, "JustConn") 
        else:
                         
            print('closing', conn)
            #even if no cancel_sub messsage has been sended
            #it's still needed to remove the socket from the data structures      
            self.readCancelSub(conn)
            self.sel.unregister(conn)
            conn.close()

    def readPubSub(self,conn,method,topic,msg=None):
        #use regex in order to do the publish/subscribe operations
        newTopic=False
        topics=topic.split("/")
        topics[0]="root"
        if topics[1]=="":
            topics=["root"]
        users=[]
        topic_name=""
        for i in range(len(topics)):
            topic_name+="/"+str(topics[i])
            if topic_name not in self.topicmsg:
                self.topicmsg[topic_name]={}
                self.topicmsg[topic_name]["messages"]=[]
                self.topicmsg[topic_name]["users"]=[]
                if i!=0:
                    newTopic=True
                    newTopic=self.listTopics(newTopic, conn) #everytime a topic its created, we send the List of Topics to The User before publishing the message
            self.topicmsg[topic_name]["users"]=self.topicmsg[topic_name]["users"]+list(set(users)-set(self.topicmsg[topic_name]["users"]))
            users=users+list(set(self.topicmsg[topic_name]["users"])-set(users))#pass all users from topic to subtopic, removing duplicates
            #publish msg    
            if msg != None:
                #print(topic_name)
                #we just save the last message from each topic
                self.topicmsg[topic_name]["messages"].append(str(msg))
                if len(self.topicmsg[topic_name]["messages"])>1:
                     self.topicmsg[topic_name]["messages"].pop(0)

        #now we can send the message ...             
        if msg!=None:        
                self.sendtoTopic(topic_name)
        #subscribe topic
        else:
            #search for subscription topic(subtopics too)
            for topic in self.topicmsg.keys():
                if topic_name in topic:
                    self.topicmsg[topic]["users"].append(conn)
                    if topic!="/root":
                        msg_to_send=self.topicmsg[topic]["messages"]
                        if len(msg_to_send)>0:
                            #send Last saved messsage,when subscribed to a topic with messages saved
                            self.sendMsg(conn,"LAST_MSG", topic[5:len(topic)], msg_to_send[len(msg_to_send)-1])
        newTopic=self.listTopics(newTopic, conn) #everytime a topic its created, we send the List of Topics to The User 

    def sendtoTopic(self, topic_name):
        #Publish Message for all users in the topic, and its subtopics
        for user in self.topicmsg[topic_name]["users"]:
            msg=self.topicmsg[topic_name]["messages"][len(self.topicmsg[topic_name]["messages"])-1]
            self.sendMsg(user,"PUBLISH",topic_name[5:len(topic_name)],msg)    

    def readCancelSub(self,conn,canceltopic=None):
        for topic in self.topicmsg:
            #if it has been sended a cancel subscription message only remove 
            # the subcription to that topic and subtopics(if they exist)
            if(canceltopic != None):
                if conn in self.topicmsg[topic]["users"] and ("/root"+canceltopic) in topic :
                    self.topicmsg[topic]["users"].remove(conn)
            else:
            #if not, then when closing the connection we need to remove the socket from the dictionary anyways
            # which avoids a publisher send a message to a closed socket
                if conn in self.topicmsg[topic]["users"]:
                    self.topicmsg[topic]["users"].remove(conn)
        if conn in self.usersdict:
            del self.usersdict[conn]  
    
    def listTopics(self, newTopic, conn, conn_Spec=None):
        #list all topics in Broker after a subscription and after a new topic has been created
        #informing all online users
        if newTopic==True:
            users=[conn]
            lst=""
            for key,value in self.topicmsg.items():
                if key!="/root":
                    lst+="Topic: "+str(key[5:len(key)])+"\\n"
                    users=users+list(set(value["users"])-set(users))
            if conn_Spec==None:
                users.remove(conn)
            else:
                users=[conn]
            if len(users)>0:
                for user in users:
                    if(len(lst)>0):
                        self.sendMsg(user,'LIST_ACK',"\\nList of Topics:","\\n"+str(lst))        
                    else:
                        #subscription to the root does not count as a topic
                        self.sendMsg(user,'LIST_NACK',"\\nList of Topics:","\\nNo topics created yet.\\n") 
        return False

    def decodeJSON(self, data):
        data=data.decode('utf-8')
        msg=json.loads(data)
        op=msg['method']
        topic=msg['topic']
        msg=msg['msg']
        return op,topic,msg  
    def encodeJSON(self, method, topic,msg):
        init={'method':method,'topic':topic,'msg':msg}
        init=json.dumps(init)
        init=init.encode('utf-8')
        return init
    def encodePICKLE(self,method, topic,msg):
        init={'method':method,'topic':topic,'msg':msg}
        init=pickle.dumps(init)
        return init
    def decodePICKLE(self,data):
        msg=pickle.loads(data)
        op=msg['method']
        topic=msg['topic']
        msg=msg['msg']
        return op,topic,msg   
    def encodeXML(self,method,topic,msg):
        init={'method':method,'topic':topic,'msg':msg}
        init=('<?xml version="1.0"?><data method="%(method)s" topic="%(topic)s"><msg>%(msg)s</msg></data>' % init)
        init=init.encode('utf-8')
        return init
    def decodeXML(self,data):
        init=data.decode('utf-8')
        init=ET.fromstring(init)
        init2=init.attrib
        op=init2['method']
        topic=init2['topic']
        msg=init.find('msg').text
        return op,topic,msg

    def run(self):
        #use selectors to registers the events on Broker
        self.sel.register(self.sock, selectors.EVENT_READ, self.accept)
        while True:
            events = self.sel.select()
            for key, mask in events:
                callback = key.data
                callback(key.fileobj, mask)    

if __name__ == "__main__":
    br=Broker()