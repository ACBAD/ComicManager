import json
import os
import subprocess
from typing import Iterable, Set
import boto3
import botocore.exceptions
from botocore.config import Config
from boto3.s3.transfer import TransferConfig
from tqdm import tqdm

# 配置Cloudflare R2的凭证和参数
# noinspection SpellCheckingInspection

with open('r2.json', 'r') as conf_f:
    r2_conf = json.load(conf_f)
    access_key_id = r2_conf['access_key_id']
    secret_access_key = r2_conf['secret_access_key']
    endpoint_url = r2_conf['endpoint_url']
    bucket_name = r2_conf['bucket_name']
    region_name = r2_conf['region_name']
    bucket_url = r2_conf['bucket_url']

proxy_config = Config(proxies={'http': 'http://127.0.0.1:10809',
                               'https': 'http://127.0.0.1:10809'})

s3 = boto3.client('s3', endpoint_url=endpoint_url,
                  aws_access_key_id=access_key_id,
                  aws_secret_access_key=secret_access_key, config=proxy_config)

script_dir = os.path.dirname(os.path.abspath(__file__))

cwd = os.getcwd()
if cwd != script_dir:
    os.chdir(script_dir)
    print(f"cd to script_dir: {script_dir}")


def abort_abnormal_uploads():
    """终止未完成的多部分上传"""
    response = s3.list_multipart_uploads(Bucket=bucket_name)
    if 'Uploads' in response:
        uploads = response['Uploads']
        for upload in uploads:
            upload_id = upload['UploadId']
            key = upload['Key']
            # 终止未完成的多部分上传
            s3.abort_multipart_upload(Bucket=bucket_name, Key=key, UploadId=upload_id)
            print(f"已终止未完成的多部分上传：Key={key}, UploadId={upload_id}")
    else:
        print("没有未完成的多部分上传。")


class TqdmProgress(tqdm):
    """自定义进度条更新"""

    def __init__(self, filename, initial=0):
        self.filename = filename
        self.total = os.path.getsize(filename)
        super().__init__(total=self.total,
                         initial=initial,
                         unit='B',
                         unit_scale=True,
                         unit_divisor=1024,
                         desc=os.path.basename(filename))

    def update_to(self, bytes_amount):
        self.update(bytes_amount)


def get_uploaded_size(file_path):
    """获取已上传文件的大小，支持正在进行的上传"""
    try:
        # 获取正在进行的多部分上传
        response = s3.list_multipart_uploads(Bucket=bucket_name)
        for upload in response.get('Uploads', []):
            if upload['Key'] == file_path:
                # 获取正在上传的文件的 UploadId
                upload_id = upload['UploadId']
                # 列出已上传的分片
                parts = s3.list_parts(Bucket=bucket_name, Key=file_path, UploadId=upload_id)
                uploaded_size = sum(part['Size'] for part in parts.get('Parts', []))
                return uploaded_size
        # 如果没有正在进行的上传，返回0
        return 0
    except botocore.exceptions.ClientError as e:
        print(f"检查已上传文件大小时出错：{e}")
        return 0


def file_exists(remote_file):
    """检查文件是否已上传完成"""
    try:
        # 获取文件元数据
        s3.head_object(Bucket=bucket_name, Key=remote_file)
        return True
    except botocore.exceptions.ClientError as e:
        # 文件不存在，返回 False
        if e.response['Error']['Code'] == '404':
            return False
        print(f"检查文件是否存在时出错：{e}")
        return False


def uploadFile(local_path, remote_path=None, recovery=False):
    """上传文件，支持断点续传和多线程上传"""
    if remote_path is None:
        remote_path = local_path
    if file_exists(remote_path) and not recovery:
        return True
    uploaded_size = get_uploaded_size(remote_path)
    try:
        with TqdmProgress(local_path, initial=uploaded_size) as progress_bar:
            config = TransferConfig(
                multipart_threshold=5 * 1024 * 1024,
                multipart_chunksize=5 * 1024 * 1024,
                max_concurrency=4,
                use_threads=True
            )
            s3.upload_file(local_path,
                           bucket_name,
                           remote_path,
                           Config=config,
                           Callback=progress_bar.update_to)
            return True
    except Exception as e:
        print(f"文件上传失败：{e}")
        return False


def moveFile(src_path, dst_path):
    copy_source = {
        'Bucket': bucket_name,
        'Key': src_path
    }
    try:
        copy_result = s3.copy_object(CopySource=copy_source, Bucket=bucket_name, Key=dst_path)
        if copy_result['ResponseMetadata']['HTTPStatusCode'] >= 300:
            raise ConnectionError(f'{copy_result["ResponseMetadata"]}')
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
    delete_result = s3.delete_object(Bucket=bucket_name, Key=src_path)
    if delete_result['ResponseMetadata']['HTTPStatusCode'] >= 300:
        raise ConnectionError(f'{delete_result["ResponseMetadata"]}')
    return True


def uploadFolder(folder_path):
    files = os.listdir(folder_path)
    for file in files:
        uploadFile(f'{folder_path}/{file}', f'{folder_path}/{file}')


def remove_file(file_path):
    result = s3.delete_object(Bucket=bucket_name, Key=file_path)
    if result['ResponseMetadata']['HTTPStatusCode'] < 300:
        return True
    return False


def download(files: Iterable[str], dl_dir, callback=None, use_proxy='http://127.0.0.1:10809'):
    if os.getenv('PYCHARM_HOSTED') == '1':
        raise EnvironmentError('PyCharm Hosted, cannot run aria2c in pycharm')
    if not isinstance(files, Iterable):
        raise RuntimeError("files must be Iterable")
    if os.name == 'nt':
        aria2_name = '.\\aria2c.exe'
    elif os.name == 'posix':
        aria2_name = 'aria2c'
    else:
        raise NotImplementedError("Unsupported platform")
    if os.name == 'nt' and not os.path.exists(aria2_name):
        raise FileNotFoundError("aria2c not found in current directory")
    urls = [bucket_url + f for f in files]
    aria_cmd = [
        aria2_name,
        '--dir', dl_dir,
        '-x', '16',
        '-s', '16',
        '--summary-interval=0',
        '-i', '-'
    ]
    if use_proxy:
        aria_cmd.append('--all-proxy')
        aria_cmd.append(use_proxy)
    try:
        process = subprocess.Popen(
            aria_cmd,
            stdin=subprocess.PIPE,
            stdout=None if callback else subprocess.DEVNULL,
            stderr=None if callback else subprocess.DEVNULL,
            text=True  # 允许传递字符串而非bytes
        )
        process.communicate(input='\n'.join(urls))
        return process.returncode
    except Exception as e:
        print(e)
        return False


def listFiles(folder_path) -> Set[str]:
    all_files = set()
    continuation_token = None
    while True:
        list_kwargs = dict(MaxKeys=1000, Prefix=folder_path, Bucket=bucket_name)
        if continuation_token:
            list_kwargs['ContinuationToken'] = continuation_token
        response = s3.list_objects_v2(**list_kwargs)
        all_files |= {file['Key'] for file in response.get('Contents', [])}
        if not response.get('IsTruncated'):  # At the end of the list?
            break
        continuation_token = response.get('NextContinuationToken')
    return all_files


# move_file('mujica_s1e7.mp4', 'mujica/mujica_s1e7.mp4')
# abort_abnormal_uploads()
if __name__ == '__main__':
    uploadFile("test.zip")
