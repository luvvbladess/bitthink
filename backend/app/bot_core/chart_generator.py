"""
Модуль для генерации графиков и диаграмм на основе данных.
Использует matplotlib и seaborn для создания качественных изображений.
"""

import io
import logging
from typing import List, Dict, Any, Union, Optional

logger = logging.getLogger(__name__)

def generate_chart(
    data: List[Dict[str, Any]], 
    title: str = "Анализ данных", 
    chart_type: str = "bar", 
    x_label: str = "", 
    y_label: str = "",
    label_key: str = "label",
    value_key: str = "value"
) -> Optional[bytes]:
    """
    Создает график на основе переданных данных.
    """
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
        
        # Настройка шрифтов для кириллицы
        try:
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Liberation Sans']
        except Exception:
            pass

        if not data:
            return None

        # Установка стиля (Светлая тема по просьбе пользователя)
        sns.set_theme(style="whitegrid", palette="muted")
        plt.figure(figsize=(10, 6))
        
        # Извлекаем списки меток и значений
        labels = [str(item.get(label_key, "")) for item in data]
        values = []
        for item in data:
            val = item.get(value_key, 0)
            try:
                # Пытаемся привести к числу, если это строка с пробелами (как в примере юзера)
                if isinstance(val, str):
                    val = float(val.replace(" ", "").replace(",", "."))
                values.append(float(val))
            except (ValueError, TypeError):
                values.append(0)

        # Отрисовка в зависимости от типа
        if chart_type == "bar":
            ax = sns.barplot(x=labels, y=values)
            plt.xticks(rotation=45, ha='right')
            # Добавляем подписи значений сверху столбиков
            for i, v in enumerate(values):
                ax.text(i, v, f"{v:,.0f}".replace(",", " "), color='black', ha="center", va="bottom", fontsize=9)
                
        elif chart_type == "line":
            sns.lineplot(x=labels, y=values, marker='o', linewidth=2.5)
            plt.xticks(rotation=45, ha='right')
            # Точки со значениями
            for i, v in enumerate(values):
                plt.text(labels[i], v, f"{v:,.0f}".replace(",", " "), ha="center", va="bottom")
                
        elif chart_type == "pie":
            # Для круговой диаграммы лучше не брать слишком много сегментов
            if len(labels) > 8:
                # Группируем мелкие в "Прочее"
                sorted_zip = sorted(zip(values, labels), reverse=True)
                top_values = [x[0] for x in sorted_zip[:7]]
                top_labels = [x[1] for x in sorted_zip[:7]]
                other_val = sum([x[0] for x in sorted_zip[7:]])
                if other_val > 0:
                    top_values.append(other_val)
                    top_labels.append("Прочие")
                values, labels = top_values, top_labels

            plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140, shadow=False)
            plt.axis('equal')  # Равные оси для круга
        
        plt.title(title, fontsize=14, pad=20, fontweight='bold')
        plt.xlabel(x_label, fontsize=12)
        plt.ylabel(y_label, fontsize=12)
        plt.tight_layout()
        
        # Сохранение в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120)
        plt.close() # Важно закрыть фигуру, чтобы не текла память
        
        buf.seek(0)
        return buf.getvalue()
        
    except Exception as e:
        logger.error(f"Error generating chart: {e}")
        plt.close()
        return None
