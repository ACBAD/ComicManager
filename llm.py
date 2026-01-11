try:
    from openai import AsyncOpenAI
    from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
    # noinspection PyProtectedMember
    from openai.types.responses.response_format_text_config_param import ResponseFormatJSONObject
except ImportError:
    raise ModuleNotFoundError('未安装openai库, 无法启用llm功能')
from setup_logger import get_logger
import os
import asyncio
from typing import cast

logger = get_logger('LLM')

api_key = os.getenv('CM_LLM_API_KEY')
base_url = os.getenv('CM_LLM_BASE_URL')
if base_url:
    logger.warning(f'暂不支持手动配置base url, 已切换为默认ds')
    base_url = 'https://api.deepseek.com'
else:
    base_url = 'https://api.deepseek.com'

if not api_key:
    raise ValueError('未配置API KEY, 无法启用llm功能')


async def extract_title(origin_title: str):
    pass


async def test():
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    message_list = [
        ChatCompletionSystemMessageParam(role='system', content="You are a helpful assistant."),
        ChatCompletionUserMessageParam(role='user', content='Hello with json format'),
    ]
    chat_msgs = await client.chat.completions.create(
        model="deepseek-chat",
        messages=message_list,
        stream=False,
        response_format=ResponseFormatJSONObject(type='json_object')
    )
    print(chat_msgs.choices[0].message.content)


if __name__ == '__main__':
    asyncio.run(test())
