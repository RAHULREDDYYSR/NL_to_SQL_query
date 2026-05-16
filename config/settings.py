import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "3"))

def get_supabase_client():
    import supabase
    return supabase.create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def get_openai_client():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=OPENAI_MODEL, temperature=0)