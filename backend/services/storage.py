from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Union
from config import settings
import os
import shutil


class FileStorage(ABC):
    """文件存储接口"""
    
    @abstractmethod
    def save(self, file_path: str, content: Union[str, bytes]) -> str:
        """保存文件
        
        Args:
            file_path: 文件路径
            content: 文件内容
            
        Returns:
            保存后的文件路径
        """
        pass
    
    @abstractmethod
    def read(self, file_path: str) -> Union[str, bytes]:
        """读取文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件内容
        """
        pass
    
    @abstractmethod
    def delete(self, file_path: str) -> bool:
        """删除文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否删除成功
        """
        pass
    
    @abstractmethod
    def exists(self, file_path: str) -> bool:
        """检查文件是否存在
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件是否存在
        """
        pass

    @abstractmethod
    def delete_dir(self, dir_path: str) -> bool:
        """删除整个目录及其内容
        
        Args:
            dir_path: 目录路径
            
        Returns:
            是否删除成功
        """
        pass


class LocalFileStorage(FileStorage):
    """本地磁盘存储实现"""
    
    def __init__(self):
        """初始化本地存储"""
        # 确保存储目录存在
        settings.DOC_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    
    def save(self, file_path: str, content: Union[str, bytes]) -> str:
        """保存文件到本地磁盘"""
        # 构建完整路径
        full_path = settings.DOC_STORAGE_DIR / file_path
        
        # 确保父目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        if isinstance(content, str):
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        else:
            with open(full_path, 'wb') as f:
                f.write(content)
        
        return str(file_path)
    
    def read(self, file_path: str) -> Union[str, bytes]:
        """从本地磁盘读取文件"""
        # 构建完整路径
        full_path = settings.DOC_STORAGE_DIR / file_path
        
        # 检查文件是否存在
        if not full_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 读取文件
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            # 如果是二进制文件
            with open(full_path, 'rb') as f:
                return f.read()
    
    def delete(self, file_path: str) -> bool:
        """从本地磁盘删除文件"""
        # 构建完整路径
        full_path = settings.DOC_STORAGE_DIR / file_path
        
        # 检查文件是否存在
        if not full_path.exists():
            return False
        
        # 删除文件
        try:
            full_path.unlink()
            return True
        except Exception:
            return False
    
    def exists(self, file_path: str) -> bool:
        """检查文件是否存在"""
        full_path = settings.DOC_STORAGE_DIR / file_path
        return full_path.exists()

    def delete_dir(self, dir_path: str) -> bool:
        """删除本地磁盘上的整个目录及其内容"""
        full_path = settings.DOC_STORAGE_DIR / dir_path
        if not full_path.exists() or not full_path.is_dir():
            return False
        try:
            shutil.rmtree(full_path)
            return True
        except Exception:
            return False


class OSSFileStorage(FileStorage):
    """OSS存储实现（可选）"""
    
    def __init__(self):
        """初始化OSS存储"""
        try:
            import oss2
        except ImportError:
            raise ImportError("OSS存储需要安装aliyun-oss-python-sdk包")
        
        # 验证OSS配置
        if not all([settings.OSS_ENDPOINT, settings.OSS_ACCESS_KEY_ID, 
                   settings.OSS_ACCESS_KEY_SECRET, settings.OSS_BUCKET_NAME]):
            raise ValueError("OSS存储配置不完整")
        
        # 创建OSS客户端
        auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
        self.bucket = oss2.Bucket(auth, settings.OSS_ENDPOINT, settings.OSS_BUCKET_NAME)
    
    def save(self, file_path: str, content: Union[str, bytes]) -> str:
        """保存文件到OSS"""
        # 构建OSS对象键
        oss_key = settings.OSS_PREFIX + file_path
        
        # 转换内容为字节
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        # 上传文件
        self.bucket.put_object(oss_key, content)
        
        return file_path
    
    def read(self, file_path: str) -> Union[str, bytes]:
        """从OSS读取文件"""
        # 构建OSS对象键
        oss_key = settings.OSS_PREFIX + file_path
        
        # 下载文件
        try:
            content = self.bucket.get_object(oss_key).read()
            
            # 尝试解码为字符串
            try:
                return content.decode('utf-8')
            except UnicodeDecodeError:
                return content
        except oss2.exceptions.NoSuchKey:
            raise FileNotFoundError(f"文件不存在: {file_path}")
    
    def delete(self, file_path: str) -> bool:
        """从OSS删除文件"""
        # 构建OSS对象键
        oss_key = settings.OSS_PREFIX + file_path
        
        # 删除文件
        try:
            self.bucket.delete_object(oss_key)
            return True
        except oss2.exceptions.NoSuchKey:
            return False
        except Exception:
            return False
    
    def exists(self, file_path: str) -> bool:
        """检查文件是否存在"""
        # 构建OSS对象键
        oss_key = settings.OSS_PREFIX + file_path
        
        # 检查文件是否存在
        try:
            self.bucket.head_object(oss_key)
            return True
        except oss2.exceptions.NoSuchKey:
            return False

    def delete_dir(self, dir_path: str) -> bool:
        """删除 OSS 上某个前缀下的所有文件（模拟删除目录）"""
        oss_prefix = settings.OSS_PREFIX + dir_path.rstrip('/') + '/'
        try:
            for obj in oss2.ObjectIterator(self.bucket, prefix=oss_prefix):
                self.bucket.delete_object(obj.key)
            return True
        except Exception:
            return False


def get_storage() -> FileStorage:
    """根据配置获取存储实例
    
    Returns:
        FileStorage实例
    """
    storage_type = settings.STORAGE_TYPE.lower()
    
    if storage_type == "local":
        return LocalFileStorage()
    elif storage_type == "oss":
        return OSSFileStorage()
    else:
        raise ValueError(f"不支持的存储类型: {storage_type}")


# 创建全局存储实例
storage = get_storage()
