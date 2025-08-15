# chat/management/commands/opensearch_service.py
from django.core.management.base import BaseCommand
from chat.services.opensearch_recommender import recommend_with_knn

class Command(BaseCommand):
    help = "인덱싱된 벡터로 k-NN 검색하여 추천문을 출력합니다."

    def add_arguments(self, parser):
        parser.add_argument('query', type=str)
        parser.add_argument('--top_k', type=int, default=3)
        parser.add_argument('--index', type=str, default=None)

    def handle(self, *args, **opts):
        text = recommend_with_knn(
            query=opts['query'],
            top_k=opts['top_k'],
            index_name=opts['index'],
        )
        # 표준출력으로만 내보내되, 핵심 로직은 서비스로 이동했으므로 중복X
        self.stdout.write(text)
