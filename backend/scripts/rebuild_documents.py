#!/usr/bin/env python3
"""
文档重建脚本
用于从output目录重建文档信息到数据库
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import settings, init_logger
from services.database import db

# 初始化日志记录器
logger = init_logger(__name__)

# 输出目录
OUTPUT_DIR = settings.OUTPUT_DIR

def rebuild_documents_from_output():
    """从output目录重建文档信息到数据库"""
    if not OUTPUT_DIR.exists():
        logger.warning(f"Output目录不存在: {OUTPUT_DIR}")
        return
    
    logger.info(f"开始从output目录重建文档信息到数据库")
    
    # 遍历output目录下的所有子目录（每个子目录对应一个文件ID）
    for item in OUTPUT_DIR.iterdir():
        if item.is_dir():
            file_id = item.name
            # 检查数据库中是否已存在
            existing_doc = db.get_document(file_id)
            if not existing_doc:
                # 检查是否存在markdown文件
                markdown_path = item / "extracted.md"
                if markdown_path.exists():
                    # 重建文档信息到数据库
                    db.add_document(
                        document_id=file_id,
                        filename=f"{file_id}.pdf",
                        file_path=str(item / f"{file_id}.pdf"),
                        markdown_path=str(markdown_path),
                        images_dir=str(item / "images") if (item / "images").exists() else None,
                        status="parsed"
                    )
                    logger.info(f"重建文件ID: {file_id} 的文档信息到数据库")
    
    # 统计数据库中的文档数量
    all_docs = db.get_all_documents()
    logger.info(f"重建完成，数据库中共 {len(all_docs)} 个文档")

if __name__ == "__main__":
    rebuild_documents_from_output()
