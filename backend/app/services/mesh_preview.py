"""Build a self-contained viewer from bounded, numeric mesh data."""
import base64
import io
import json
import math
import stat
import struct
import zipfile
import zlib
from pathlib import Path, PurePosixPath


SUFFIXES = {'.obj', '.stl', '.glb'}
MAX_BYTES = 20 * 1024 * 1024
MAX_TRIANGLES = 350_000
_GLB_JSON = 0x4E4F534A
_GLB_BIN = 0x004E4942
_COMPONENT = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
_TYPE_COUNT = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def find_preview(files):
    """Prefer standalone meshes, then inspect a bounded set of ZIP members as data."""
    meshes = []
    for name, data in files:
        suffix = Path(name).suffix.lower()
        if suffix in SUFFIXES:
            meshes.append((name, data))
    for name, data in sorted(meshes, key=lambda mesh: not mesh[0].lower().endswith('.obj'))[:4]:
        preview = build(name, data)
        if preview:
            return name, preview

    remaining_bytes = 2 * MAX_BYTES
    archives = (data for name, data in files if Path(name).suffix.lower() == '.zip'
                and 0 < len(data) <= 2 * MAX_BYTES)
    for data in list(archives)[:3]:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) > 1000:
                    continue
                candidates = []
                for member in members:
                    path = PurePosixPath(member.filename)
                    if (not member.is_dir() and path.suffix.lower() in SUFFIXES
                            and not path.is_absolute() and '..' not in path.parts
                            and not any(char in member.orig_filename for char in '\\\0:')
                            and not stat.S_ISLNK(member.external_attr >> 16)
                            and not member.flag_bits & 1 and 0 < member.file_size <= MAX_BYTES):
                        candidates.append((path, member))
                for path, member in sorted(candidates, key=lambda pair: pair[0].suffix.lower() != '.obj')[:4]:
                    if member.file_size > remaining_bytes:
                        continue
                    remaining_bytes -= member.file_size
                    preview = build(path.name, archive.read(member))
                    if preview:
                        return path.name, preview
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, zlib.error):
            continue
    return None


def _point(values):
    point = tuple(map(float, values))
    if len(point) != 3 or any(not math.isfinite(v) or abs(v) > 1e12 for v in point):
        raise ValueError('Invalid mesh vertex')
    return point


def _obj(data):
    vertices, colors, triangles, groups = [], {}, [], []
    group = 'Модель'
    for line in data.decode('utf-8-sig', errors='replace').splitlines():
        fields = line.partition('#')[0].split(maxsplit=1)
        if not fields:
            continue
        kind, *args = fields
        if kind == 'v':
            values = args[0].split()
            if len(values) == 6:
                rgb = _point(values[3:])
                if all(0 <= value <= 1 for value in rgb):
                    colors[len(vertices)] = rgb
            vertices.append(_point(values[:3]))
            if len(vertices) > 3 * MAX_TRIANGLES:
                raise ValueError('Too many mesh vertices')
        elif kind in ('o', 'g') and args:
            group = args[0][:72]
        elif kind == 'f':
            face = []
            for token in args[0].split():
                index = int(token.split('/', 1)[0])
                if index == 0 or index < -len(vertices) or index > len(vertices):
                    raise ValueError('Invalid OBJ index')
                face.append(index - 1 if index > 0 else len(vertices) + index)
            if len(face) < 3 or len(triangles) + len(face) - 2 > MAX_TRIANGLES:
                raise ValueError('Invalid or oversized OBJ face')
            if not groups or groups[-1][0] != group:
                groups.append([group, len(triangles), *([colors[face[0]]] if face[0] in colors else [])])
            # shortcut: fan triangulation expects convex polygons, export a triangle mesh for concave faces.
            triangles.extend((vertices[face[0]], vertices[face[i]], vertices[face[i + 1]]) for i in range(1, len(face) - 1))
    return triangles, groups


def _stl(data):
    count = struct.unpack_from('<I', data, 80)[0] if len(data) >= 84 else 0
    if count and len(data) == 84 + 50 * count:
        if count > MAX_TRIANGLES:
            raise ValueError('Too many STL triangles')
        triangles = [
            tuple(_point(facet[i:i + 3]) for i in (3, 6, 9))
            for facet in struct.iter_unpack('<12fH', memoryview(data)[84:])
        ]
    else:
        points = []
        for line in data.decode('ascii').splitlines():
            fields = line.split()
            if fields and fields[0].lower() == 'vertex':
                points.append(_point(fields[1:]))
                if len(points) > 3 * MAX_TRIANGLES:
                    raise ValueError('Too many STL vertices')
        if len(points) % 3:
            raise ValueError('Incomplete STL triangle')
        triangles = list(zip(points[::3], points[1::3], points[2::3]))
    return triangles, [['Модель', 0]]


def _glb_parts(data):
    if len(data) < 20 or data[:4] != b'glTF':
        raise ValueError('Not a GLB')
    version, length = struct.unpack_from('<II', data, 4)
    if version != 2 or not 20 <= length <= len(data):
        raise ValueError('Bad GLB header')
    offset, document, blob = 12, None, None
    while offset + 8 <= length:
        size, kind = struct.unpack_from('<II', data, offset)
        offset += 8
        if size < 0 or offset + size > length:
            raise ValueError('Truncated GLB chunk')
        chunk = data[offset:offset + size]
        offset += size
        if kind == _GLB_JSON:
            document = json.loads(chunk.decode('utf-8'))
        elif kind == _GLB_BIN:
            blob = chunk
    if not isinstance(document, dict) or blob is None:
        raise ValueError('GLB has no mesh payload')
    return document, blob


def _accessor(document, blob, index):
    accessors, views = document.get('accessors') or [], document.get('bufferViews') or []
    if not isinstance(index, int) or not 0 <= index < len(accessors):
        raise ValueError('Bad GLB accessor')
    accessor = accessors[index]
    if not isinstance(accessor, dict) or accessor.get('sparse') is not None:
        raise ValueError('Unsupported GLB accessor')
    view_index = accessor.get('bufferView')
    if not isinstance(view_index, int) or not 0 <= view_index < len(views):
        raise ValueError('Bad GLB buffer view')
    view = views[view_index]
    if not isinstance(view, dict) or view.get('buffer', 0) != 0:
        raise ValueError('External GLB buffer')
    components = _TYPE_COUNT.get(accessor.get('type'))
    layout = _COMPONENT.get(accessor.get('componentType'))
    count = accessor.get('count')
    if not components or not layout or not isinstance(count, int) or count < 0 or count > 3 * MAX_TRIANGLES:
        raise ValueError('Unsupported GLB accessor')
    fmt, width = layout
    start = int(view.get('byteOffset') or 0) + int(accessor.get('byteOffset') or 0)
    stride = int(view.get('byteStride') or 0) or width * components
    if start < 0 or stride < width * components or start + max(count - 1, 0) * stride + width * components > len(blob):
        raise ValueError('GLB accessor is outside the buffer')
    return [struct.unpack_from('<' + fmt * components, blob, start + i * stride) for i in range(count)]


def _glb(data):
    document, blob = _glb_parts(data)
    triangles, groups = [], []
    for mesh in document.get('meshes') or []:
        if not isinstance(mesh, dict):
            continue
        name = str(mesh.get('name') or 'Модель')[:72]
        for primitive in mesh.get('primitives') or []:
            if not isinstance(primitive, dict) or primitive.get('mode', 4) != 4:
                continue
            attributes = primitive.get('attributes') or {}
            if not isinstance(attributes, dict) or 'POSITION' not in attributes:
                continue
            try:
                points = [_point(item[:3]) for item in _accessor(document, blob, attributes['POSITION'])]
                raw = _accessor(document, blob, primitive['indices']) if 'indices' in primitive else [(i,) for i in range(len(points))]
                indices = [int(item[0]) for item in raw]
            except (ValueError, IndexError, TypeError, struct.error):
                continue
            if len(indices) < 3 or len(indices) % 3 or len(triangles) + len(indices) // 3 > MAX_TRIANGLES:
                continue
            added = []
            valid = True
            for offset in range(0, len(indices), 3):
                face = indices[offset:offset + 3]
                if any(index < 0 or index >= len(points) for index in face):
                    valid = False
                    break
                added.append(tuple(points[index] for index in face))
            if not valid or not added:
                continue
            if not groups or groups[-1][0] != name:
                groups.append([name, len(triangles)])
            triangles.extend(added)
    if not triangles:
        raise ValueError('GLB has no triangles')
    return triangles, groups


def _geometry(filename, data):
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES or not 0 < len(data) <= MAX_BYTES:
        return None
    try:
        triangles, groups = {'.obj': _obj, '.stl': _stl, '.glb': _glb}[suffix](data)
    except (ValueError, IndexError, TypeError, struct.error, json.JSONDecodeError):
        return None
    if not triangles:
        return None
    vertices = [point for triangle in triangles for point in triangle]
    bounds = [(min(axis), max(axis)) for axis in zip(*vertices)]
    span = max(hi - lo for lo, hi in bounds)
    if span <= 0:
        return None
    center = [(lo + hi) / 2 for lo, hi in bounds]
    return suffix, vertices, groups, center, span


def build(filename, data):
    geometry = _geometry(filename, data)
    if geometry is None:
        return None
    suffix, vertices, groups, center, span = geometry
    packed = bytearray(6 * len(vertices))
    for i, point in enumerate(vertices):
        struct.pack_into('<3h', packed, 6 * i, *(round(32767 * (v - c) / span) for v, c in zip(point, center)))
    compressed = len(packed) > 256 * 1024
    if len(groups) > 512:
        groups = [['Модель', 0]]
    payload = json.dumps({'data': base64.b64encode(zlib.compress(packed, 1) if compressed else packed).decode('ascii'),
                          'compressed': compressed, 'groups': groups,
                          'name': Path(filename).stem[:100], 'format': suffix[1:].upper()}).replace('<', '\\u003c')
    return TEMPLATE.replace('__MESH_DATA__', payload).encode('utf-8')


def review_image(filename, data):
    """Three small fixed-camera views of the exported geometry for the reviewer."""
    from io import BytesIO
    from PIL import Image, ImageDraw

    geometry = _geometry(filename, data)
    if geometry is None:
        return None
    _, vertices, _, center, span = geometry
    points = [tuple((v - c) / span for v, c in zip(point, center)) for point in vertices]
    panel = 280
    image = Image.new('RGB', (panel * 3, panel), '#161c1e')
    draw = ImageDraw.Draw(image)
    for index, (name, yaw) in enumerate((('Front', 0), ('Three-quarter', -.6), ('Side', math.pi / 2))):
        c, s = math.cos(yaw), math.sin(yaw)
        tilt = .28 if index == 1 else 0
        e, f = math.sin(tilt), math.cos(tilt)
        projected = []
        for x, y, z in points:
            depth = x * s + y * c
            projected.append(((index + .5) * panel + (x * c - y * s) * 174,
                              panel * .53 - (z * f + depth * e) * 174, z * e - depth * f))
        triangles = sorted(zip(projected[::3], projected[1::3], projected[2::3]),
                           key=lambda t: sum(p[2] for p in t))
        for a, b, c in triangles:
            ux, uy, uz = (b[k] - a[k] for k in range(3))
            vx, vy, vz = (c[k] - a[k] for k in range(3))
            nx, ny, nz = (uy * vz - uz * vy) * 174, (uz * vx - ux * vz) * 174, ux * vy - uy * vx
            norm = math.hypot(nx, ny, nz)
            if not norm or not nz:
                continue
            shade = round(92 + 140 * abs((.24 * nx - .38 * ny + .87 * nz) / norm))
            draw.polygon([p[:2] for p in (a, b, c)], fill=(shade, shade, shade))
        draw.text((index * panel + 12, 12), name, fill='#f2f4f5')
    buffer = BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


TEMPLATE = Path(__file__).with_name('mesh_preview.html').read_text(encoding='utf-8')
