"""Build and verify one parametric FreeCAD plate in a private output directory."""
import json
import math
from pathlib import Path
import sys


def build(values, output):
    length, width, thickness, diameter, inset = (
        values[key] for key in ('length_mm', 'width_mm', 'thickness_mm', 'hole_diameter_mm', 'edge_inset_mm')
    )
    if any(not math.isfinite(value) or not 0.1 <= value <= 1000 for value in values.values()):
        raise ValueError('Каждый размер должен быть от 0,1 до 1000 мм.')
    if inset <= diameter / 2 or min(length, width) - 2 * inset <= diameter:
        raise ValueError('Отверстия пересекаются или выходят за края пластины.')

    sys.path.insert(0, '/usr/lib/freecad-python3/lib')
    import FreeCAD as App
    import Part

    doc = App.newDocument('MountingPlate')
    base = doc.addObject('Part::Box', 'BasePlate')
    base.Label = 'Пластина'
    base.Length, base.Width, base.Height = length, width, thickness
    base.addProperty('App::PropertyLength', 'HoleDiameter', 'Отверстия')
    base.addProperty('App::PropertyLength', 'HoleInset', 'Отверстия')
    base.HoleDiameter, base.HoleInset = diameter, inset
    holes = []
    for x in ('BasePlate.HoleInset', 'BasePlate.Length - BasePlate.HoleInset'):
        for y in ('BasePlate.HoleInset', 'BasePlate.Width - BasePlate.HoleInset'):
            hole = doc.addObject('Part::Cylinder', f'Hole{len(holes) + 1}')
            hole.setExpression('Radius', 'BasePlate.HoleDiameter / 2')
            hole.setExpression('Height', 'BasePlate.Height')
            hole.setExpression('Placement.Base.x', x)
            hole.setExpression('Placement.Base.y', y)
            holes.append(hole)
    pattern = doc.addObject('Part::Compound', 'HolePattern')
    pattern.Label = 'Четыре сквозных отверстия'
    pattern.Links = holes
    plate = doc.addObject('Part::Cut', 'FinishedPlate')
    plate.Label = 'Готовая пластина'
    plate.Base, plate.Tool = base, pattern
    doc.recompute()

    volume = (length * width - math.pi * diameter ** 2) * thickness
    centers = [(x, y) for x in (inset, length - inset) for y in (inset, width - inset)]

    def verify(shape):
        if shape.isNull() or not shape.isValid() or len(shape.Solids) != 1:
            raise RuntimeError('FreeCAD не подтвердил одно корректное твёрдое тело.')
        size = (shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength)
        if (not all(math.isclose(actual, expected, abs_tol=1e-5)
                    for actual, expected in zip(size, (length, width, thickness)))
                or not math.isclose(shape.Volume, volume, abs_tol=1e-5, rel_tol=1e-7)
                or any(shape.isInside(App.Vector(x, y, z), 1e-6, False)
                       for x, y in centers for z in (thickness * .25, thickness * .75))):
            raise RuntimeError('Фактическая геометрия не совпала с заданными размерами.')
        return {'bounds_mm': list(size), 'volume_mm3': shape.Volume, 'through_holes': len(centers)}

    measured = verify(plate.Shape)
    doc.saveAs(str(output / 'mounting-plate.FCStd'))
    plate.Shape.exportStep(str(output / 'mounting-plate.step'))
    verify(Part.read(str(output / 'mounting-plate.step')))
    geometry = {
        'size': measured['bounds_mm'],
        'centers': [[hole.Placement.Base.x, hole.Placement.Base.y] for hole in holes],
        'radius': holes[0].Radius.Value,
        'inset': base.HoleInset.Value,
        'volume': measured['volume_mm3'],
    }
    template = Path(__file__).with_name('preview.html').read_text(encoding='utf-8')
    (output / 'mounting-plate.html').write_text(template.replace('__GEOMETRY__', json.dumps(geometry)), encoding='utf-8')
    print(json.dumps({'dimensions_mm': values, 'measured': measured, 'step_verified': True,
                      'freecad_version': '.'.join(App.Version()[:3])}))


if __name__ == '__main__':
    try:
        build(json.loads(sys.argv[1]), Path.cwd())
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
