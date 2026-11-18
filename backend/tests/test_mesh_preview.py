import base64
import io
import json
import struct
import zipfile
import zlib

from app.services.mesh_preview import build, find_preview, review_image
from canvas_intent import explicitly_text_only


def test_mesh_validation_request_does_not_opt_out_of_canvas():
    assert not explicitly_text_only('Сделай модель. Проверь форму и приложи OBJ.')
    assert explicitly_text_only('Сделай модель OBJ, без холста.')


def test_obj_preview_uses_parts_and_never_embeds_html():
    obj = b'# test\no base\nv 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\no </script><img>\nf -4 -2 -1\n'
    page = build('model.obj', obj)
    assert b'["base", 0]' in page
    assert b'["\\u003c/script>\\u003cimg>", 1]' in page
    assert b'__MESH_DATA__' not in page
    assert build('model.obj', obj + b'f 1 2 10000\n') is None


def test_stl_preview_handles_binary_and_ascii():
    binary = bytes(80) + struct.pack('<I12fH', 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
    ascii_stl = b'solid test\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendsolid\n'
    assert b'"format": "STL"' in build('part.STL', binary)
    assert b'"format": "STL"' in build('part.stl', ascii_stl)
    assert build('part.stl', binary[:-2]) is None


def test_colored_obj_parts_and_rendered_review():
    data = b'o cast\nv 0 0 0 .1 .5 .2\nv 1 0 0 .1 .5 .2\nv 0 1 0 .1 .5 .2\nf 1 2 3\n'
    assert b'["cast", 0, [0.1, 0.5, 0.2]]' in build('test.obj', data)
    assert review_image('test.obj', data).startswith(b'\x89PNG\r\n\x1a\n')


def test_larger_preview_uses_compressed_geometry():
    data = b'v 0 0 0\nv 1 0 0\nv 0 1 0\n' + b'f 1 2 3\n' * 15_000
    page = build('test.obj', data)
    payload = json.loads(page.split(b'const model = ', 1)[1].split(b';\n', 1)[0])
    assert payload['compressed']
    raw = zlib.decompress(base64.b64decode(payload['data']))
    assert len(raw) == 15_000 * 3 * 6
    assert struct.unpack_from('<3h', raw) == (-16384, -16384, 0)


def _glb(positions, indices, name='hull'):
    blob = b''.join(struct.pack('<3f', *point) for point in positions)
    blob += b''.join(struct.pack('<H', index) for index in indices)
    document = {
        'asset': {'version': '2.0'},
        'buffers': [{'byteLength': len(blob)}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': len(positions) * 12},
            {'buffer': 0, 'byteOffset': len(positions) * 12, 'byteLength': len(indices) * 2},
        ],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': len(positions), 'type': 'VEC3'},
            {'bufferView': 1, 'componentType': 5123, 'count': len(indices), 'type': 'SCALAR'},
        ],
        'meshes': [{'name': name, 'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
    }
    payload = json.dumps(document, separators=(',', ':')).encode()
    payload += b' ' * ((4 - len(payload) % 4) % 4)
    chunks = struct.pack('<II', len(payload), 0x4E4F534A) + payload
    chunks += struct.pack('<II', len(blob), 0x004E4942) + blob
    return b'glTF' + struct.pack('<II', 2, 12 + len(chunks)) + chunks


def test_glb_preview_opens_on_the_canvas():
    data = _glb(((0, 0, 0), (1, 0, 0), (0, 1, 0)), (0, 1, 2), 'aurora')
    page = build('aurora_cruiser.glb', data)
    assert b'"format": "GLB"' in page
    assert b'["aurora", 0]' in page
    assert find_preview([('notes.txt', b'hi'), ('aurora_cruiser.glb', data)])[0] == 'aurora_cruiser.glb'
    assert build('broken.glb', b'glTF' + b'\0' * 16) is None


def test_zip_mesh_preview_ignores_unsafe_paths_and_other_members():
    obj = b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('../unsafe.obj', obj)
        archive.writestr('code.py', b'not executed')
        archive.writestr('exports/Lathe.obj', obj)
    zipped = buffer.getvalue()
    assert find_preview([('bundle.zip', zipped)])[0] == 'Lathe.obj'
    assert find_preview([('bundle.zip', zipped), ('standalone.obj', obj)])[0] == 'standalone.obj'
    assert find_preview([('broken.zip', b'PK'), ('README.txt', obj)]) is None
