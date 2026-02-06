from dotenv import load_dotenv

# Load .env before any test module's skipif markers evaluate os.getenv.
load_dotenv()
