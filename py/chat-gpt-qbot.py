import json
import uuid
import requests
import os
import traceback
from text_to_image import text_to_image
from flask import request, Flask
from revChatGPT.revChatGPT import Chatbot, generate_uuid

with open("config.json", "r") as jsonfile:
    config_data = json.load(jsonfile)
    qq_config = config_data["qq_bot"]
    chat_gpt_config = config_data["chatGPT"]
    qq_no = qq_config['qq_no']
    cqhttp_url = qq_config['cqhttp_url']
    if chat_gpt_config['session_token'] != "":
        config = {
            "session_token": chat_gpt_config['session_token']
        }
    else:
        config = {
            "email": chat_gpt_config['email'],
            "password": chat_gpt_config['password']
        }
    config['cf_clearance'] = chat_gpt_config['cf_clearance']
    config['user_agent'] = chat_gpt_config['user_agent']
    max_length = qq_config['max_length']
    image_path = qq_config['image_path']

# 创建一个服务，把当前这个python文件当做一个服务
server = Flask(__name__)
# 创建ChatGPT实例
chatbot = Chatbot(config, conversation_id=None)
# 存放session
sessions = {}


# 与ChatGPT交互的方法
def chat(msg, sessionid):
    try:
        if msg.strip() == '':
            return '您好，我是人工智能助手，如果您有任何问题，请随时告诉我，我将尽力回答。\n如果您需要重置我们的会话，请回复`重置会话`'
        # 获得对话session
        session = get_chat_session(sessionid)
        if '重置会话' == msg.strip():
            session.reset_conversation()
            return "会话已重置"
        # 与ChatGPT交互获得对话内容
        message = session.get_chat_response(msg)
        print("会话ID: " + str(sessionid))
        print("ChatGPT返回内容: ")
        print(message)
        return message
    except Exception as error:
        chatbot.refresh_session()
        traceback.print_exc()
        return str('异常: ' + str(error) + '\n如果报错持续出现，请对我发送 `重置会话`')


# 测试接口，可以用来测试与ChatGPT的交互是否正常，用来排查问题
@server.route('/chat', methods=['post'])
def chatapi():
    requestJson = request.get_data()
    if requestJson is None or requestJson == "" or requestJson == {}:
        resu = {'code': 1, 'msg': '请求内容不能为空'}
        return json.dumps(resu, ensure_ascii=False)
    data = json.loads(requestJson)
    print(data)
    try:
        msg = chat(data['msg'], '11111111')
        resu = {'code': 0, 'data': msg}
        return json.dumps(resu, ensure_ascii=False)
    except Exception as error:
        print("接口报错")
        resu = {'code': 1, 'msg': '请求异常: ' + str(error)}
        return json.dumps(resu, ensure_ascii=False)


# 测试接口，可以测试本代码是否正常启动
@server.route('/', methods=["GET"])
def index():
    return f"你好，QQ机器人逻辑处理端已启动<br/>"


# qq消息上报接口，qq机器人监听到的消息内容将被上报到这里
@server.route('/', methods=["POST"])
def get_message():
    if request.get_json().get('message_type') == 'private':  # 如果是私聊信息
        uid = request.get_json().get('sender').get('user_id')  # 获取信息发送者的 QQ号码
        message = request.get_json().get('raw_message')  # 获取原始信息
        sender = request.get_json().get('sender')  # 消息发送者的资料
        print("收到私聊消息：")
        print(message)
        # 下面你可以执行更多逻辑，这里只演示与ChatGPT对话
        msg_text = chat(message, 'P' + str(uid))  # 将消息转发给ChatGPT处理
        send_private_message(uid, msg_text)  # 将消息返回的内容发送给用户

    if request.get_json().get('message_type') == 'group':  # 如果是群消息
        gid = request.get_json().get('group_id')  # 群号
        uid = request.get_json().get('sender').get('user_id')  # 发言者的qq号
        message = request.get_json().get('raw_message')  # 获取原始信息
        # 判断当被@时才回答
        if str("[CQ:at,qq=%s]" % qq_no) in message:
            sender = request.get_json().get('sender')  # 消息发送者的资料
            print("收到群聊消息：")
            print(message)
            message = str(message).replace(str("[CQ:at,qq=%s]" % qq_no), '')
            # 下面你可以执行更多逻辑，这里只演示与ChatGPT对话
            msg_text = chat(message, 'G' + str(gid))  # 将消息转发给ChatGPT处理
            send_group_message(gid, msg_text, uid)  # 将消息转发到群里

    if request.get_json().get('post_type') == 'request':  # 收到请求消息
        print("收到请求消息")
        request_type = request.get_json().get('request_type')  # group
        uid = request.get_json().get('user_id')
        flag = request.get_json().get('flag')
        comment = request.get_json().get('comment')
        if request_type == "friend":
            print("收到加好友申请")
            print("QQ：", uid)
            print("验证信息", comment)
            # 直接同意，你可以自己写逻辑判断是否通过
            set_friend_add_request(flag, "true")
        if request_type == "group":
            print("收到群请求")
            sub_type = request.get_json().get('sub_type')  # 两种，一种的加群(当机器人为管理员的情况下)，一种是邀请入群
            gid = request.get_json().get('group_id')
            if sub_type == "add":
                # 如果机器人是管理员，会收到这种请求，请自行处理
                print("收到加群申请，不进行处理")
            elif sub_type == "invite":
                print("收到邀请入群申请")
                print("群号：", gid)
                # 直接同意，你可以自己写逻辑判断是否通过
                set_group_invite_request(flag, "true")
    return "ok"


# 发送私聊消息方法 uid为qq号，message为消息内容
def send_private_message(uid, message):
    try:
        if len(message) >= max_length:  # 如果消息长度超过限制，转成图片发送
            pic_path = genImg(message)
            message = "[CQ:image,file=" + pic_path + "]"
        res = requests.post(url=cqhttp_url + "/send_private_msg",
                            params={'user_id': int(uid), 'message': message}).json()
        if res["status"] == "ok":
            print("私聊消息发送成功")
        else:
            print(res)
            print("私聊消息发送失败，错误信息：" + str(res['wording']))

    except Exception as error:
        print("私聊消息发送失败")
        print(error)


# 发送群消息方法
def send_group_message(gid, message, uid):
    try:
        if len(message) >= max_length:  # 如果消息长度超过限制，转成图片发送
            pic_path = genImg(message)
            message = "[CQ:image,file=" + pic_path + "]"
        message = str('[CQ:at,qq=%s]\n' % uid) + message  # @发言人
        res = requests.post(url=cqhttp_url + "/send_group_msg",
                            params={'group_id': int(gid), 'message': message}).json()
        if res["status"] == "ok":
            print("群消息发送成功")
        else:
            print("群消息发送失败，错误信息：" + str(res['wording']))
    except Exception as error:
        print("群消息发送失败")
        print(error)


# 处理好友请求
def set_friend_add_request(flag, approve):
    try:
        requests.post(url=cqhttp_url + "/set_friend_add_request", params={'flag': flag, 'approve': approve})
        print("处理好友申请成功")
    except:
        print("处理好友申请失败")


# 处理邀请加群请求
def set_group_invite_request(flag, approve):
    try:
        requests.post(url=cqhttp_url + "/set_group_add_request",
                      params={'flag': flag, 'sub_type': 'invite', 'approve': approve})
        print("处理群申请成功")
    except:
        print("处理群申请失败")


# 对话session
class ChatSession:
    def __init__(self):
        self.parent_id = None
        self.conversation_id = None
        self.reset_conversation()

    # 重置对话方法
    def reset_conversation(self):
        self.conversation_id = None
        self.parent_id = generate_uuid()

    # 获取对话内容方法
    def get_chat_response(self, message):
        try:
            chatbot.conversation_id = self.conversation_id
            chatbot.parent_id = self.parent_id
            return chatbot.get_chat_response(message)['message']
        finally:
            self.conversation_id = chatbot.conversation_id
            self.parent_id = chatbot.parent_id


# 获取对话session
def get_chat_session(sessionid):
    if sessionid not in sessions:
        sessions[sessionid] = ChatSession()
    return sessions[sessionid]


# 生成图片
def genImg(message):
    img = text_to_image(message)
    filename = str(uuid.uuid1()) + ".png"
    filepath = image_path + str(os.path.sep) + filename
    img.save(filepath)
    print("图片生成完毕: " + filepath)
    return filename


# 以流的方式对话
def printMessage():
    text = ''
    for i in chatbot.get_chat_response("你好", output="stream"):
        print(str(i['message']).replace(text, ''))
        text = i['message']


# 测试接口
@server.route('/test', methods=["GET"])
def test():
    printMessage()
    return f"ok"


if __name__ == '__main__':
    server.run(port=7777, host='0.0.0.0', use_reloader=False)
