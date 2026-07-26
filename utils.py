import enum
import pydantic
from pydantic import BaseModel
from pathlib import Path
from setup_logger import getLogger
import fastapi
import json

logger, setLoggerLevel, _ = getLogger('SiteUtils')


class UserAbilities(enum.Enum):
    CREATE_DOCUMENT = 'document.create'
    DELETE_DOCUMENT = 'document.delete'
    CREATE_TAG = 'tag.create'
    DELETE_TAG = 'tag.delete'
    CREATE_SOURCE = 'source.create'


class UserInfo(BaseModel):
    username: str
    abilities: list[UserAbilities]
    admin: bool = False

    @property
    def is_admin(self):
        return self.admin

    def has_ability(self, ability: UserAbilities):
        return ability in self.abilities


class UserConfig(BaseModel):
    users: dict[str, UserInfo]


auth_file_path = Path('auth.json')
auth_config: UserConfig | None = None
if auth_file_path.exists():
    with open(auth_file_path) as pwd_f:
        auth_file_content = pwd_f.read()
        try:
            auth_config = UserConfig.model_validate(json.loads(auth_file_content))
        except (pydantic.ValidationError, json.JSONDecodeError) as ve:
            logger.warning(f'认证文件不合规, 将忽略: {ve}')
else:
    logger.warning('认证文件未配置, 默认允许所有人进行任何操作')


async def get_current_user(request: fastapi.Request) -> UserInfo | None:
    token = request.cookies.get("auth_token")
    if auth_config is None:
        return UserInfo(username='__DEFAULT_ADMIN__', admin=True, abilities=[])
    if not token:
        return None
    user = auth_config.users.get(token, None)
    if not user:
        return None
    return user


class Authoricator:
    def __init__(
            self,
            required_abilities: list[UserAbilities] | None = None,
    ):
        self.required_abilities = required_abilities

    async def __call__(self, user: UserInfo = fastapi.Depends(get_current_user)) -> UserInfo | None:
        if user is None:
            raise fastapi.HTTPException(status_code=fastapi.status.HTTP_401_UNAUTHORIZED, detail='需要登录, 或用户不存在')
        if user.admin:
            return user
        if self.required_abilities is None:
            return user
        for ability in self.required_abilities:
            if not user.has_ability(ability):
                raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN,
                                            detail=f'当前操作需要权限: {ability}, 用户 {user.username}无该权限')
        return user
