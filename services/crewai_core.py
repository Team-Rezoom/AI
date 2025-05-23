import logging
import time
import json
from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
import re



llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

# Agent 정의
gap_analyzer = Agent(
    role="Gap Analyzer",
    goal="개선 포인트 도출",
    backstory="이력서/자소서 평가 결과를 분석하여 부족한 점을 도출합니다.",
    llm=llm,
    verbose=True
)

learning_coach = Agent(
    role="Learning Coach",
    goal="학습 계획 추천",
    backstory="분석된 부족한 항목에 대해 학습 계획을 제안합니다.",
    llm=llm,
    verbose=True
)



# CrewAI 결과 검증 (Discriminator 역할)
def verify_crew_output(resume_eval: str, selfintro_eval: str, gap_text: str, plan_text: str) -> dict:
    prompt = f"""
    다음은 AI가 생성한 이력서 개선 분석 결과와 학습 로드맵입니다.
    이 결과가 실제 평가 결과와 비교했을 때 타당하고 설득력 있는지 검토해주세요.

    [이력서 평가 결과]
    {resume_eval}

    [자기소개서 평가 결과]
    {selfintro_eval}

    [Gap 분석 결과]
    {gap_text}

    [학습 로드맵]
    {plan_text}

    응답은 반드시 다음 JSON 형식의 코드블럭으로만 주세요 (설명 없이):
    {{
        "verdict": "YES" 또는 "NO",
        "reason": "간단한 사유"
    }}
    """
    raw = llm.invoke(prompt)
    content = raw.content if hasattr(raw, "content") else raw
    logging.info(f"[verify_crew_output] LLM 응답 원문:\n{content}")
    return extract_json_from_response(content)

    


# CrewAi 실행
async def analyze_with_raw_output(resume_eval: str, selfintro_eval: str) -> dict:
    try:
        overall_start = time.time()

        # 1. Task 구성
        t1 = time.time()
        task1 = Task(
            description=f"""
                다음 이력서/자소서 평가 결과를 분석해, 개선이 필요한 기술, 경험, 자격 요건을 항목별로 제시하세요.

                - 출력은 순수 텍스트 형식으로 제공해주세요.
                - 마크다운 기호(예: '-', '*', '**', '#') 또는 개행(\\n)은 사용하지 마세요.
                - 각 항목은 숫자로 구분된 문장으로 작성해주세요. (예: 1. ~, 2. ~)
                - 불필요한 서식이나 장식 없이, 자연스러운 한글 문장으로 기술해주세요.

                [이력서 평가]
                {resume_eval}

                [자기소개서 평가]
                {selfintro_eval}

                출력 예시:
                1. React 프로젝트 경험을 추가로 서술해야 합니다.
                2. 자기소개서에 본인의 역할과 기여도를 구체적으로 작성하세요.
            """,
            expected_output="개선 포인트 리스트",
            agent=gap_analyzer
        )

        task2 = Task(
            description="""
                앞선 항목을 기반으로 학습 로드맵을 작성해주세요 (2~4주 계획).

                - 출력 형식은 아래와 같은 JSON 구조로 제공해주세요.
                - 마크다운(예: **굵게**, -, \\n 등)은 절대 사용하지 마세요.
                - HTML, 마크업 없이 순수한 텍스트 값만 포함해주세요.

                예시:
                {
                    "weeks": [
                        {
                            "week": "1주차",
                            "focus": "React 기초 학습",
                            "tasks": [
                                "JSX 문법 익히기",
                                "useState, 이벤트 핸들링 실습"
                            ]
                        },
                        ...
                    ]
                }
            """,
            expected_output="주차별 학습 계획",
            agent=learning_coach
        )
        t2 = time.time()
        print(f"[Task 구성] {t2 - t1:.2f}초")

        # 2. Crew 실행
        t3 = time.time()
        crew = Crew(
            agents=[gap_analyzer, learning_coach],
            tasks=[task1, task2],
            verbose=True
        )
        await crew.kickoff_async()
        t4 = time.time()
        print(f"[Crew 실행] {t4 - t3:.2f}초")

        # 3. 출력 추출
        gap = str(task1.output.raw_output if hasattr(task1.output, "raw_output") else task1.output)
        plan = str(task2.output.raw_output if hasattr(task2.output, "raw_output") else task2.output)

        # 4. 검증
        evaluation = verify_crew_output(
            resume_eval=resume_eval,
            selfintro_eval=selfintro_eval,
            gap_text=gap,
            plan_text=plan
        )

        overall_end = time.time()
        print(f"[전체 소요 시간] {overall_end - overall_start:.2f}초")

        
        logging.info("[analyze_with_raw_output] 완료")
        return {
            "gap": gap,
            "plan": plan,
            "evaluation": evaluation
        }

    except Exception as e:
        logging.error(f"에러 발생: {e}")
        raise
    

# 둘다 상, 둘중 하나 하 아닌 경우
def generate_simple_feedback(resume_eval: str, selfintro_eval: str) -> str:
    
    prompt = f"""
        다음 이력서/자기소개서 평가를 바탕으로 간단한 개선 조언 2~3줄을 작성해주세요.
            - 출력은 순수 텍스트 형식으로 제공해주세요.
            - 마크다운 기호(예: '-', '*', '**', '#') 또는 개행(\\n)은 사용하지 마세요.
            - 각 항목은 숫자로 구분된 문장으로 작성해주세요. (예: 1. ~, 2. ~)
            - 불필요한 서식이나 장식 없이, 자연스러운 한글 문장으로 기술해주세요.

        [이력서 평가]
        {resume_eval}

        [자기소개서 평가]
        {selfintro_eval}
        
        출력 예시:
            1. React 프로젝트 경험을 추가로 서술해야 합니다.
            2. 자기소개서에 본인의 역할과 기여도를 구체적으로 작성하세요.
    """
    return llm.invoke(prompt)


def extract_json_from_response(content: str) -> str:
    try:
        # 코드블록 안 JSON 찾기
        matches = re.findall(r'```json\\s*({.*?})\\s*```', content, re.DOTALL)
        if matches:
            return json.loads(matches[0])
        
        # 일반 JSON 블럭 찾기
        json_start = content.find('{')
        json_end = content.rfind('}') + 1
        if json_start != -1 and json_end != -1:
            return json.loads(content[json_start:json_end])
        
    except Exception as e:
        logging.warning(f"[extract_json] JSON 파싱 실패: {e}")

    return {"verdict": "NO", "reason": "LLM 응답이 JSON 형식이 아님"}

def self_intro_rewriter(resume_text: str) -> str:
    prompt = f"""
    아래 자기소개서를 읽고 감점 요소가 될 수 있는 문장을 최대 3~5개 선정해주세요.

    각 문장에 대해 다음과 같은 방식으로 작성하세요:
    1. 원문 문장을 그대로 제시하고
    2. 감점 사유를 간결히 설명하며
    3. 보다 나은 인상을 줄 수 있는 개선 문장을 제안하세요.

    반드시 아래 형식을 따르세요 (번호 순서, 들여쓰기 포함):
    
    1. 원문: ...
       - 감점 사유: ...
       - 개선 제안: ...
    
    반드시 지켜야 할 규칙:
    - 마크다운 기호(예: '-', '*', '**', '#') 또는 개행(\\n)은 사용하지 마세요.
    - 불필요한 서식이나 장식 없이, 자연스러운 한글 문장으로 기술해주세요.
    - JSON 형식, 코드블럭 형식 없이 순수한 텍스트로만 작성하세요.

    [자기소개서 원문]
    {resume_text}
    """
    response = llm.invoke(prompt)
    return response.content.strip()
