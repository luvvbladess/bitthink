"""Run: python -m unittest discover -s sandbox -p test_diagrams.py -v.
Set DRAWIO_BINARY to also exercise the real installed renderer (Windows or Linux).
"""
import ast
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services import diagrams, workspace_fs

XML = '''<mxfile><diagram name="Схема"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="n" parent="1" vertex="1" value="Проверка &amp; результат" style="rounded=1;whiteSpace=wrap;html=1;fontSize=18;">
<mxGeometry x="40" y="40" width="260" height="80" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>'''


class DiagramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bt-diagrams-test-')
        self.env = patch.dict(os.environ, WORKSPACES_DIR=self.temp.name)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_native_source_and_chat_delivery(self):
        response = json.loads(workspace_fs.dispatch(11, 'diagram', {'path': 'Схемы/Процесс.drawio', 'xml': XML, 'formats': []}))
        self.assertEqual(response['files'], ['Схемы/Процесс.drawio'])
        files = json.loads(workspace_fs.collect_deliverables(11))
        self.assertEqual([f['name'] for f in files], ['Процесс.drawio'])
        self.assertEqual(base64.b64decode(files[0]['data_b64']).decode(), XML)
        # SVG must be downloadable even when no PDF was requested.
        svg = workspace_fs.user_root(11) / 'Тест.svg'
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assertIn('Тест.svg', [f['name'] for f in json.loads(workspace_fs.collect_deliverables(11))])

    def test_no_overwrite_and_existing_export_copy(self):
        args = {'path': 'original.drawio', 'xml': XML, 'formats': []}
        diagrams.create_diagram(11, args)
        with self.assertRaises(ValueError):
            diagrams.create_diagram(11, args)
        diagrams.create_diagram(11, {'path': 'copy.drawio', 'source_path': 'original.drawio', 'formats': []})
        self.assertEqual((workspace_fs.user_root(11) / 'original.drawio').read_text(encoding='utf-8'), XML)

    def test_invalid_xml_references_external_resources_and_empty_pages(self):
        invalid = ['<mxfile>', '<svg/>', '<!DOCTYPE x><mxfile/>',
                   '<mxfile><diagram>compressed</diagram></mxfile>',
                   XML.replace('id="n"', 'id="1"'), XML.replace('parent="1" vertex', 'parent="missing" vertex'),
                   XML.replace('rounded=1', 'image=http://127.0.0.1/private'),
                   XML.replace('Проверка &amp; результат', '&lt;img src="file:///etc/passwd"&gt;')]
        for value in invalid:
            with self.subTest(xml=value), self.assertRaises(ValueError):
                diagrams.validate_xml(value)

    def test_user_boundary_and_format_validation(self):
        for changes in [{'path': '../u12/leak.drawio'}, {'path': '/tmp/leak.drawio'},
                        {'formats': ['exe']}, {'page_index': 2}, {'page_index': True},
                        {'xml': XML, 'source_path': 'other.drawio'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                diagrams.create_diagram(11, {'path': 'new.drawio', 'xml': XML, 'formats': [], **changes})
        self.assertFalse(list(workspace_fs.user_root(11).glob('*.drawio')))

    def test_failed_export_does_not_deliver_partial_files(self):
        with patch.dict(os.environ, DRAWIO_BINARY='fake-drawio'), patch.object(diagrams, '_export', side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):
                diagrams.create_diagram(11, {'path': 'failed.drawio', 'xml': XML})
        self.assertEqual(json.loads(workspace_fs.collect_deliverables(11)), [])

    def test_tool_transport_and_old_client_isolation(self):
        tools = (ROOT / 'backend/app/bot_core/computer_tools.py').read_text(encoding='utf-8')
        ast.parse(tools)
        self.assertIn('DIAGRAM_SPEC,', tools)
        self.assertIn("names.discard('diagram_create')", tools)
        client = (ROOT / 'backend/app/services/sandbox_client.py').read_text(encoding='utf-8')
        self.assertIn('"diagram_create": "diagram"', client)
        self.assertIn('"diagram_create"', (ROOT / 'backend/app/api/desktop.py').read_text(encoding='utf-8'))

    def test_web_mode_routing(self):
        spec = importlib.util.spec_from_file_location('diagram_mode_switch', ROOT / 'backend/app/bot_core/mode_switch.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for request in ['Нарисуй блок-схему проверки заказа', 'Создай схему процесса в diagrams.net']:
            suggestion = module.suggest_mode_switch('auto', request, allowed={'auto', 'director'})
            self.assertEqual(suggestion['model'], 'director')
            self.assertIn('.drawio', suggestion['reason'])
            self.assertIsNone(module.suggest_mode_switch('director', request, allowed={'director'}))
        self.assertIsNone(module.suggest_mode_switch('auto', 'Объясни блок-схему', allowed={'auto', 'director'}))

    def test_export_formats_do_not_become_document_package(self):
        import re
        source = (ROOT / 'backend/app/bot_core/director_router.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_is_document_package_task')
        namespace = {'re': re}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<diagram-routing-test>', 'exec'), namespace)
        self.assertFalse(namespace['_is_document_package_task']('Нарисуй блок-схему и выдай четыре файла PDF PNG SVG drawio'))

    @unittest.skipUnless(os.environ.get('DRAWIO_BINARY'), 'requires native draw.io')
    def test_real_renderer_multipage_pdf_png_svg_and_delivery(self):
        # Keep the second page unique, with an easy-to-check SVG label.
        second = XML[:-len('</mxfile>')] + XML[XML.index('<diagram'):].replace('Проверка &amp; результат', 'ВТОРАЯ СТРАНИЦА')
        result = json.loads(diagrams.create_diagram(11, {'path': 'Готовая.drawio', 'xml': second,
                                                         'formats': ['pdf', 'png', 'svg'], 'page_index': 2}))
        self.assertEqual(result['pages'], 2)
        files = json.loads(workspace_fs.collect_deliverables(11))
        self.assertEqual({Path(f['name']).suffix for f in files}, {'.drawio', '.pdf', '.png', '.svg'})
        self.assertIn('ВТОРАЯ СТРАНИЦА', (workspace_fs.user_root(11) / 'Готовая.svg').read_text(encoding='utf-8'))
        print('Native web export verified:', workspace_fs.user_root(11))


if __name__ == '__main__':
    unittest.main()
