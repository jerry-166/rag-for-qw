import os
import time
import requests
import zipfile
import io
import uuid
from pathlib import Path

from config import settings

class PDFParser:
    def __init__(self):
        # 配置MinerU API
        self.MINERU_BASE_URL = settings.MINERU_BASE_URL
        self.MINERU_API_KEY = settings.MINERU_API_KEY
        if not self.MINERU_API_KEY:
            raise ValueError("MINERU_API_KEY 环境变量未设置")
        
        # 输出目录
        self.OUTPUT_DIR = settings.OUTPUT_DIR
        self.OUTPUT_DIR.mkdir(exist_ok=True)
    
    def parse_pdf(self, pdf_path):
        """解析PDF文件并返回Markdown内容"""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")
        
        pdf_name = pdf_path.name
        
        # 创建输出目录
        md_output_dir = self.OUTPUT_DIR / pdf_path.stem
        md_output_dir.mkdir(parents=True, exist_ok=True)
        md_output_path = md_output_dir / "extracted.md"
        
        # 1. 获取上传URL
        print("正在获取上传URL...")
        headers = {
            "Authorization": f"Bearer {self.MINERU_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            url=f"{self.MINERU_BASE_URL}/api/v4/file-urls/batch",
            headers=headers,
            json={
                "files": [{"name": pdf_name, "data_id": pdf_name}],
                "model_version": "vlm",
            }
        )
        response.raise_for_status()
        
        data = response.json()["data"]
        batch_id = data["batch_id"]
        file_urls = data["file_urls"]
        
        print(f"获取上传URL成功，batch_id: {batch_id}")
        
        # 2. 上传PDF文件
        print("正在上传PDF文件到MinerU的URL中...")
        with open(pdf_path, "rb") as f:
            file_data = f.read()
            upload_response = requests.put(file_urls[0], data=file_data)
            upload_response.raise_for_status()
        
        print("PDF文件上传成功！")
        
        # 3. 轮询检查处理状态
        print("正在轮询检查处理状态...")
        
        max_wait = settings.MAX_WAIT_TIME  # 最长等待时间（秒）
        poll_interval = settings.POLL_INTERVAL  # 轮询间隔（秒）
        elapsed = 0
        full_zip_url = None
        
        while elapsed < max_wait:
            status_response = requests.get(
                f"{self.MINERU_BASE_URL}/api/v4/extract-results/batch/{batch_id}",
                headers={"Authorization": f"Bearer {self.MINERU_API_KEY}"}
            )
            
            result = status_response.json()["data"]["extract_result"][0]
            state = result["state"]
            if state == "done":
                full_zip_url = result["full_zip_url"]
                print(f"解析完成，下载链接：{full_zip_url}")
                break
            elif state == "failed":
                error_message = result.get("err_msg", "未知错误")
                print(f"解析失败：{error_message}")
                raise Exception(f"PDF解析失败: {error_message}")
            elif state == "running":
                progress = result.get("extract_progress", {})
                extracted = progress.get("extracted_pages", 0)
                total = progress.get("total_pages", "?")
                print(f"   {extracted}/{total} 页 (已等待 {elapsed}秒)", end="\r")
            
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        if elapsed >= max_wait:
            print("等待超时，未能完成解析")
            raise Exception("PDF解析超时")
        
        # 4. 下载解析结果的zip文件，并解压
        if full_zip_url:
            print("正在下载解析结果的zip文件，并解压...")
            zip_response = requests.get(full_zip_url)
            
            with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zf:
                md_files = [f for f in zf.namelist() if f.endswith(".md")]
                
                # 读取 & 下载md文件
                if md_files:
                    md_file = next((f for f in md_files if "full" in f.lower()), md_files[0])
                    with zf.open(md_file) as f:
                        md_content = f.read().decode("utf-8")
                        print(f"成功读取Markdown文件: {md_file}, 大小: {len(md_content) / 1024:.2f} KB")
                    if md_content:
                        with open(md_output_path, "w", encoding="utf-8") as f:
                            f.write(md_content)
                        
                        print(f"Markdown内容已保存到: {md_output_dir.resolve()}")
                        print(f"内容预览：{md_content[:500]}...")
                        print("-" * 100)
                else:
                    print("未找到Markdown文件")
                    raise Exception("未找到Markdown文件")
                
                # 读取 & 下载图片
                images = [f for f in zf.namelist() if f.lower().startswith("images/")]
                image_output_dir = None
                if images:
                    image_output_dir = md_output_dir / "images"
                    image_output_dir.mkdir(parents=True, exist_ok=True)
                    
                    for img in images:
                        with zf.open(img) as f:
                            img_data = f.read()
                        if img_data:
                            with open(image_output_dir / f"{str(uuid.uuid4())}.jpg", "wb") as img_f:
                                img_f.write(img_data)
                        else:
                            print(f"警告：未能读取图片数据: {img}")
                    print(f"成功下载并保存 {len(images)} 张图片到: {image_output_dir.resolve()}")
                else:
                    print("未找到图片文件")
        else:
            print("未获取到解析结果的下载链接，无法继续")
            raise Exception("未获取到解析结果的下载链接")
        
        return {
            "markdown_path": str(md_output_path),
            "images_dir": str(image_output_dir) if image_output_dir else None,
            "pdf_name": pdf_name
        }
