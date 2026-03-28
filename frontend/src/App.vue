<template>
  <div class="min-h-screen flex flex-col">
    <!-- 顶部导航栏 -->
    <header class="bg-white shadow-sm">
      <div class="container mx-auto px-4 py-4 flex justify-between items-center">
        <h1 class="text-2xl font-bold text-primary">RAG System</h1>
        <nav>
          <ul class="flex space-x-6">
            <li><a href="#upload" class="text-gray-600 hover:text-primary transition-colors">上传PDF</a></li>
            <li><a href="#process" class="text-gray-600 hover:text-primary transition-colors">文档处理</a></li>
            <li><a href="#query" class="text-gray-600 hover:text-primary transition-colors">智能查询</a></li>
            <li><a href="#info" class="text-gray-600 hover:text-primary transition-colors">系统信息</a></li>
          </ul>
        </nav>
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="flex-1 container mx-auto px-4 py-8">
      <!-- 上传PDF部分 -->
      <section id="upload" class="mb-12">
        <h2 class="text-2xl font-bold mb-6">上传PDF文件</h2>
        <div class="card">
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 mb-2">选择PDF文件</label>
            <input 
              type="file" 
              accept=".pdf" 
              class="input" 
              @change="handleFileChange"
            />
          </div>
          <button 
            class="btn btn-primary" 
            @click="uploadPDF"
            :disabled="!selectedFile || isUploading"
          >
            {{ isUploading ? '上传中...' : '上传并解析' }}
          </button>
          <div v-if="uploadResult" class="mt-4 p-4 rounded-lg bg-success/10 text-success">
            <p>上传成功！文件ID: {{ uploadResult.file_id }}</p>
            <p class="text-sm mt-1">{{ uploadResult.message }}</p>
          </div>
        </div>
      </section>

      <!-- 文档处理部分 -->
      <section id="process" class="mb-12">
        <h2 class="text-2xl font-bold mb-6">文档处理</h2>
        <div class="card">
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 mb-2">文件ID</label>
            <input 
              type="text" 
              v-model="fileId" 
              class="input" 
              placeholder="请输入文件ID"
            />
          </div>
          <div class="flex space-x-4">
            <button 
              class="btn btn-primary" 
              @click="processDocument"
              :disabled="!fileId || isProcessing"
            >
              {{ isProcessing ? '处理中...' : '处理文档' }}
            </button>
            <button 
              class="btn btn-secondary" 
              @click="getMarkdown"
              :disabled="!fileId || isGettingMarkdown"
            >
              {{ isGettingMarkdown ? '获取中...' : '查看Markdown' }}
            </button>
            <button 
              class="btn btn-success" 
              @click="importToMilvus"
              :disabled="!fileId || isImporting"
            >
              {{ isImporting ? '导入中...' : '导入Milvus' }}
            </button>
          </div>
          <div v-if="processResult" class="mt-4 p-4 rounded-lg bg-success/10 text-success">
            <p>处理成功！</p>
            <p class="text-sm mt-1">段落数: {{ processResult.chunks_count }}</p>
            <p class="text-sm">子问题数: {{ processResult.sub_questions_count }}</p>
          </div>
          <div v-if="markdownContent" class="mt-4">
            <h3 class="text-lg font-semibold mb-2">Markdown内容</h3>
            <div class="border rounded-lg p-4 max-h-96 overflow-y-auto">
              <pre class="whitespace-pre-wrap">{{ markdownContent }}</pre>
            </div>
          </div>
        </div>
      </section>

      <!-- 智能查询部分 -->
      <section id="query" class="mb-12">
        <h2 class="text-2xl font-bold mb-6">智能查询</h2>
        <div class="card">
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 mb-2">查询内容</label>
            <textarea 
              v-model="queryText" 
              class="input h-32" 
              placeholder="请输入查询内容"
            ></textarea>
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 mb-2">返回结果数</label>
            <input 
              type="number" 
              v-model.number="queryLimit" 
              class="input w-24" 
              min="1" 
              max="20"
            />
          </div>
          <button 
            class="btn btn-primary" 
            @click="queryMilvus"
            :disabled="!queryText || isQuerying"
          >
            {{ isQuerying ? '查询中...' : '执行查询' }}
          </button>
          <div v-if="queryResults" class="mt-4">
            <h3 class="text-lg font-semibold mb-2">查询结果</h3>
            <div class="space-y-4">
              <div 
                v-for="(result, index) in queryResults" 
                :key="index"
                class="border rounded-lg p-4"
              >
                <p class="font-medium">相似度: {{ (result.score * 100).toFixed(2) }}%</p>
                <p class="mt-1">{{ result.text }}</p>
                <p class="text-sm text-gray-500 mt-1">来源: {{ result.metadata.source }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 系统信息部分 -->
      <section id="info" class="mb-12">
        <h2 class="text-2xl font-bold mb-6">系统信息</h2>
        <div class="card">
          <button 
            class="btn btn-secondary" 
            @click="getMilvusInfo"
            :disabled="isGettingInfo"
          >
            {{ isGettingInfo ? '获取中...' : '获取Milvus信息' }}
          </button>
          <div v-if="milvusInfo" class="mt-4">
            <h3 class="text-lg font-semibold mb-2">Milvus集合信息</h3>
            <pre class="border rounded-lg p-4 bg-gray-50 overflow-x-auto">{{ JSON.stringify(milvusInfo, null, 2) }}</pre>
          </div>
        </div>
      </section>
    </main>

    <!-- 底部版权信息 -->
    <footer class="bg-white shadow-sm py-4">
      <div class="container mx-auto px-4 text-center text-gray-500 text-sm">
        <p>© 2026 RAG System. All rights reserved.</p>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import axios from 'axios';

// 上传相关
const selectedFile = ref(null);
const isUploading = ref(false);
const uploadResult = ref(null);

// 文档处理相关
const fileId = ref('');
const isProcessing = ref(false);
const processResult = ref(null);
const isGettingMarkdown = ref(false);
const markdownContent = ref('');
const isImporting = ref(false);

// 查询相关
const queryText = ref('');
const queryLimit = ref(5);
const isQuerying = ref(false);
const queryResults = ref(null);

// 系统信息相关
const isGettingInfo = ref(false);
const milvusInfo = ref(null);

// 处理文件选择
const handleFileChange = (event) => {
  selectedFile.value = event.target.files[0];
};

// 上传PDF
const uploadPDF = async () => {
  if (!selectedFile.value) return;
  
  isUploading.value = true;
  uploadResult.value = null;
  
  try {
    const formData = new FormData();
    formData.append('file', selectedFile.value);
    
    const response = await axios.post('/api/upload/pdf', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    
    uploadResult.value = response.data;
    fileId.value = response.data.file_id; // 自动填充文件ID
  } catch (error) {
    alert('上传失败: ' + (error.response?.data?.detail || error.message));
  } finally {
    isUploading.value = false;
  }
};

// 处理文档
const processDocument = async () => {
  if (!fileId.value) return;
  
  isProcessing.value = true;
  processResult.value = null;
  
  try {
    const response = await axios.post(`/api/process/document/${fileId.value}`);
    processResult.value = response.data;
  } catch (error) {
    alert('处理失败: ' + (error.response?.data?.detail || error.message));
  } finally {
    isProcessing.value = false;
  }
};

// 获取Markdown内容
const getMarkdown = async () => {
  if (!fileId.value) return;
  
  isGettingMarkdown.value = true;
  markdownContent.value = '';
  
  try {
    const response = await axios.get(`/api/markdown/${fileId.value}`);
    markdownContent.value = response.data.content;
  } catch (error) {
    alert('获取Markdown失败: ' + (error.response?.data?.detail || error.message));
  } finally {
    isGettingMarkdown.value = false;
  }
};

// 导入到Milvus
const importToMilvus = async () => {
  if (!fileId.value) return;
  
  isImporting.value = true;
  
  try {
    const response = await axios.post(`/api/milvus/import/${fileId.value}`);
    alert('导入成功: ' + response.data.message);
  } catch (error) {
    alert('导入失败: ' + (error.response?.data?.detail || error.message));
  } finally {
    isImporting.value = false;
  }
};

// 查询Milvus
const queryMilvus = async () => {
  if (!queryText.value) return;
  
  isQuerying.value = true;
  queryResults.value = null;
  
  try {
    const response = await axios.post('/api/milvus/query', {
      query: queryText.value,
      limit: queryLimit.value
    });
    queryResults.value = response.data.results;
  } catch (error) {
    alert('查询失败: ' + (error.response?.data?.detail || error.message));
  } finally {
    isQuerying.value = false;
  }
};

// 获取Milvus信息
const getMilvusInfo = async () => {
  isGettingInfo.value = true;
  milvusInfo.value = null;
  
  try {
    const response = await axios.get('/api/milvus/info');
    milvusInfo.value = response.data.info;
  } catch (error) {
    alert('获取信息失败: ' + (error.response?.data?.detail || error.message));
  } finally {
    isGettingInfo.value = false;
  }
};
</script>

<style scoped>
/* 自定义样式 */
</style>
