from typing import List, Dict, Any
import os
import logging
import asyncio
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel
from pymongo.errors import OperationFailure
from dotenv import load_dotenv
from typing import Optional
import certifi
from openai import OpenAI
from datetime import datetime, date, time
# 환경 설정
load_dotenv()
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# MongoDB 연결
ca = certifi.where()
client = MongoClient(os.getenv("MONGODB_URI"), tlsCAFile=ca)
db = client["Rezoom"]
postings_collection = db["postings"]

# OpenAI client 초기화
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
EMBEDDING_MODEL = "text-embedding-3-small"

# MongoDB 연결 테스트
try:
    client.admin.command('ping')
    logging.info("MongoDB Atlas 연결 성공!")

    doc_count = postings_collection.count_documents({})
    logging.info(f"현재 컬렉션의 문서 수: {doc_count}")

    index_info = postings_collection.index_information()
    logging.info(f"현재 생성된 인덱스 정보:\n{index_info}")

except Exception as e:
    logging.error(f"MongoDB Atlas 연결 실패: {str(e)}")
    raise e

# 임베딩 생성 함수
async def get_embedding_async(text: str) -> List[float]:
    if not text or not text.strip():
        logging.warning("[임베딩 요청 차단] 빈 텍스트")
        return[]
    return await asyncio.to_thread(_sync_get_embedding, text)

def _sync_get_embedding(text: str) -> List[float]:
    if not text.strip():
        logging.error("임베딩 요청 텍스트가 비어 있음")
        return []
    try:
        response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[text.strip()]
        )
        embedding = response.data[0].embedding
        if not embedding or len(embedding) != 1536:
            logging.error(f"[임베딩 오류] 벡터 길이 오류: {len(embedding)}")
            return []
        return embedding
    except Exception as e:
        logging.error(f"[임베딩 생성 실패]: {e}")
        return []

# 채용공고 저장
async def store_job_posting(job_text: str, start_day: date, end_day: date) -> str:
    try:
        embedding = await get_embedding_async(job_text)
        doc = {
            "original_text": job_text,
            "embedding": embedding,
            "source": "pdf",
            "startDay": datetime.combine(start_day, time.min),
            "endDay": datetime.combine(end_day, time.min)      
        }
        result = postings_collection.insert_one(doc)
        return str(result.inserted_id)
    except Exception as e:
        logging.error(f"[PDF 채용공고 저장 실패]: {e}")
        return ""
    
    

# 문서 개수 확인
def get_document_count():
    return postings_collection.count_documents({})

# 유사도 검색 함수
async def search_similar_postings_with_score(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    query_vector = await get_embedding_async(query)
    if not query_vector:
        raise ValueError("임베딩 벡터가 비어있음 ㅎ")
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "queryVector": query_vector,
                "path": "embedding",
                "numCandidates": 100,
                "limit": top_k,
                "similarity": "cosine"
            }
        },
        {
            "$project": {
                "_id": 1,
                "title": 1,
                "description": 1,
                "url": 1,
                "score": {"$meta": "vectorSearchScore"},
                "startDay":1,
                "endDay":1
            }
        }
    ]
    return list(postings_collection.aggregate(pipeline))

# 벡터 인덱스 생성
def create_vector_index_if_not_exists():
    index_name = "vector_index"
    existing_indexes = postings_collection.list_search_indexes()
    if index_name in [idx["name"] for idx in existing_indexes]:
        logging.info(f"'{index_name}' posting 컬렉션의 인덱스 이미 존재")
        return

    index_model = SearchIndexModel(
        definition={
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": 1536,
                    "similarity": "cosine"
                }
            ]
        },
        name=index_name,
        type="vectorSearch"
    )

    try:
        postings_collection.create_search_index(model=index_model)
        logging.info(f"'{index_name}' 인덱스 생성!")
    except OperationFailure as e:
        logging.error(f"벡터 인덱스 생성 실패: {e.details}")

# 인덱스 초기화 실행
create_vector_index_if_not_exists()
