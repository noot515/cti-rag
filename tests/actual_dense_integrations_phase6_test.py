"""Opt-in real-model/Milvus checks. They are intentionally skipped in offline CI."""
import os,unittest

@unittest.skipUnless(os.getenv("CTI_RAG_RUN_ACTUAL_EMBEDDING")=="1","actual embedding runtime not requested")
class ActualEmbeddingIntegration(unittest.TestCase):
    def test_repository_embedding_model_returns_declared_dimension(self):
        from packages import config
        from packages.models.embedding import get_embedding_model
        model=get_embedding_model(config); vector=model.encode("cti-rag actual embedding smoke test")
        if isinstance(vector,(list,tuple)) and vector and isinstance(vector[0],(list,tuple)): vector=vector[0]
        self.assertEqual(len(vector),model.get_dimension())

@unittest.skipUnless(os.getenv("CTI_RAG_RUN_ACTUAL_MILVUS")=="1","actual Milvus runtime not requested")
class ActualMilvusIntegration(unittest.TestCase):
    def test_legacy_milvus_service_is_reachable(self):
        from packages.manager.milvus_manager import MilvusManager
        manager=MilvusManager(); self.assertTrue(manager.start()); self.assertEqual(manager.get_status()["status"],"running")
