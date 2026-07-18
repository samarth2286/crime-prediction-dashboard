import os
import json
import sqlite3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_client")

# --- SQL Database Connection Setup ---
SQL_DB_PATH = os.path.join(os.path.dirname(__file__), "crime_metadata.db")

def get_sql_conn():
    """Returns a standard sqlite3 connection to the structured SQL metadata database."""
    conn = sqlite3.connect(SQL_DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

# --- Persistent MongoDB Mock Implementation using SQLite ---
MOCK_MONGO_DB_PATH = os.path.join(os.path.dirname(__file__), "mongodb_mock.db")

class MockCollection:
    def __init__(self, db_name, collection_name):
        self.db_name = db_name
        self.collection_name = collection_name
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(MOCK_MONGO_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mock_mongodb_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                database_name TEXT,
                collection_name TEXT,
                data TEXT
            )
        """)
        conn.commit()
        conn.close()

    def insert_one(self, document):
        # Clean doc (remove _id if it's an ObjectId or similar since we serialize to JSON)
        doc = dict(document)
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        
        conn = sqlite3.connect(MOCK_MONGO_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO mock_mongodb_documents (database_name, collection_name, data)
            VALUES (?, ?, ?)
        """, (self.db_name, self.collection_name, json.dumps(doc)))
        conn.commit()
        conn.close()
        return type("InsertOneResult", (), {"inserted_id": doc.get("_id", "mock_id")})()

    def insert_many(self, documents):
        conn = sqlite3.connect(MOCK_MONGO_DB_PATH)
        cursor = conn.cursor()
        for document in documents:
            doc = dict(document)
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            cursor.execute("""
                INSERT INTO mock_mongodb_documents (database_name, collection_name, data)
                VALUES (?, ?, ?)
            """, (self.db_name, self.collection_name, json.dumps(doc)))
        conn.commit()
        conn.close()
        return type("InsertManyResult", (), {"inserted_ids": [d.get("_id") for d in documents]})()

    def find(self, filter_dict=None):
        conn = sqlite3.connect(MOCK_MONGO_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT data FROM mock_mongodb_documents
            WHERE database_name = ? AND collection_name = ?
        """, (self.db_name, self.collection_name))
        rows = cursor.fetchall()
        conn.close()

        results = []
        for row in rows:
            doc = json.loads(row[0])
            match = True
            if filter_dict:
                for k, v in filter_dict.items():
                    # Simple filter check for exact matching or case-insensitive matching
                    doc_val = doc.get(k)
                    if isinstance(v, dict):
                        # Handle simple operators if needed, e.g., {'$in': [...]} or {'$regex': ...}
                        if '$regex' in v:
                            import re
                            regex = re.compile(v['$regex'], re.IGNORECASE if v.get('$options') == 'i' else 0)
                            if not doc_val or not regex.search(str(doc_val)):
                                match = False
                                break
                        elif '$in' in v:
                            if doc_val not in v['$in']:
                                match = False
                                break
                    else:
                        # Exact check
                        if doc_val != v:
                            match = False
                            break
            if match:
                results.append(doc)
        return results

    def find_one(self, filter_dict=None):
        results = self.find(filter_dict)
        return results[0] if results else None

    def delete_many(self, filter_dict=None):
        # For our mock, if no filter, delete everything in the collection
        conn = sqlite3.connect(MOCK_MONGO_DB_PATH)
        cursor = conn.cursor()
        if not filter_dict:
            cursor.execute("""
                DELETE FROM mock_mongodb_documents
                WHERE database_name = ? AND collection_name = ?
            """, (self.db_name, self.collection_name))
        else:
            # Simple filtered delete: read all, filter out matching, delete and re-insert
            all_docs = self.find()
            to_keep = []
            for doc in all_docs:
                match = True
                for k, v in filter_dict.items():
                    if doc.get(k) != v:
                        match = False
                        break
                if not match:
                    to_keep.append(doc)
            
            cursor.execute("""
                DELETE FROM mock_mongodb_documents
                WHERE database_name = ? AND collection_name = ?
            """, (self.db_name, self.collection_name))
            
            for doc in to_keep:
                cursor.execute("""
                    INSERT INTO mock_mongodb_documents (database_name, collection_name, data)
                    VALUES (?, ?, ?)
                """, (self.db_name, self.collection_name, json.dumps(doc)))
                
        conn.commit()
        conn.close()
        return type("DeleteResult", (), {"deleted_count": 0})()

    def count_documents(self, filter_dict=None):
        return len(self.find(filter_dict))

class MockDatabase:
    def __init__(self, client, db_name):
        self.client = client
        self.db_name = db_name
        self.collections = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = MockCollection(self.db_name, name)
        return self.collections[name]

class MockMongoClient:
    def __init__(self, uri=None):
        self.uri = uri
        self.databases = {}

    def __getitem__(self, name):
        if name not in self.databases:
            self.databases[name] = MockDatabase(self, name)
        return self.databases[name]


# --- MongoDB Connection Function ---
def get_mongo_client():
    """
    Tries to connect to a real local MongoDB.
    Falls back to a persistent SQLite-backed mock client if MongoDB is unavailable.
    """
    import pymongo
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    
    mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    try:
        # Set a short timeout of 1.5 seconds so we don't block startup
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=1500)
        # Force a connection check
        client.admin.command('ping')
        logger.info("Connected to MongoDB successfully.")
        return client
    except (ConnectionFailure, ServerSelectionTimeoutError, Exception) as e:
        logger.warning(
            f"Could not connect to MongoDB server. Falling back to persistent SQLite-backed mock database. Details: {e}"
        )
        return MockMongoClient(mongo_uri)
