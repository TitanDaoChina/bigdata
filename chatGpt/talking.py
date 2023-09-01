import openai
from openai import InvalidRequestError

openai.api_key = "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"

session = []


def chat():
    global session
    try:
        reply = openai.ChatCompletion.create(
            model="curie:ft-personal:custom-model-name-2023-03-30-08-17-09",
            messages=session,
        )
    except InvalidRequestError as e:
        session = session[:1]
        return f"ChatGPT occur error:,{e}! Clean session"


    return reply.choices[0].message.content


if __name__ == '__main__':
    session.append({"role": "system", "content": "You are a helpful assistant."})
    while True:
        user_input = input('User: ')
        if user_input.lower() == '!quit':
            break
        elif user_input.lower() == '!clean':
            session.clear()
        elif user_input.lower().startswith("!reset "):
            session.clear()
            session.append({"role": "system", "content": user_input.replace("!reset ", "")})

        session.append({"role": "user", "content": user_input})
        response = chat()
        session.append({"role": "assistant", "content": response})
        print('ChatGPT:', response)