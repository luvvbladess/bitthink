import unittest
import app.services.product_strategy as policy


class ApiServiceStrategyTests(unittest.TestCase):
    def test_api_service_requests_are_products_with_backend_defaults(self):
        requests = [
            'Создай API-сервис для учёта датчиков',
            'Нужно создать api сервис для очереди заданий',
            'Разработай API-сервисы для обработки событий',
            'Собери API\u2011сервис для расчёта тарифов',
            'Реализуй API\u2013сервис для поиска записей',
            'Build an API service for sensor readings',
            'Create an API-service for task scheduling',
            'Implement API services for event delivery',
        ]
        for text in requests:
            with self.subTest(text=text):
                self.assertTrue(policy.is_product_request(text))
                self.assertEqual(policy.select_stack(text), 'python')

    def test_explicit_stack_still_takes_precedence(self):
        for stack, choice in [('node', 'Node.js'), ('python', 'FastAPI'),
                              ('next', 'Next.js'), ('react', 'React')]:
            text = 'Создай API-сервис для уведомлений на ' + choice
            with self.subTest(choice=choice):
                self.assertTrue(policy.is_product_request(text))
                self.assertEqual(policy.select_stack(text), stack)

    def test_explanations_and_non_creation_requests_are_not_products(self):
        for text in [
            'Объясни, как создать API-сервис',
            'Как разработать API-сервис?',
            'Explain how to build an API-service',
            'How do I create an API service?',
            'API-сервис для уведомлений',
            'Create a report about API latency',
            'Build a capi-service',
        ]:
            with self.subTest(text=text):
                self.assertFalse(policy.is_product_request(text))

    def test_existing_product_defaults_are_preserved(self):
        for text, stack in [
            ('Создай лендинг для мастерской', 'static'),
            ('Создай интернет-магазин книг', 'next'),
            ('Build a dashboard for telemetry', 'react'),
            ('Create a blog for field notes', 'astro'),
            ('Создай бота для напоминаний', 'python'),
        ]:
            with self.subTest(text=text):
                self.assertTrue(policy.is_product_request(text))
                self.assertEqual(policy.select_stack(text), stack)

    def test_empty_inputs(self):
        for text in ['', None]:
            with self.subTest(text=text):
                self.assertFalse(policy.is_product_request(text))
                self.assertEqual(policy.select_stack(text), 'static')


if __name__ == '__main__':
    unittest.main()
