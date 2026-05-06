import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from io import BytesIO

def format_minutes_to_hhmm(minutes, pos=None):
    """Convert minutes to HH:MM format"""
    if minutes < 0:
        return "0:00"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f'{hours}:{mins:02d}'

def generate_sleep_chart(sleep_data, child_name=None):
    dates = [d['date'] for d in sleep_data]
    night_min = [d['night_min'] for d in sleep_data]
    day_min = [d['day_min'] for d in sleep_data]

    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(dates))
    width = 0.5

    bars1 = ax.bar(x, night_min, width, label='Ночной сон', color='#8e44ad')
    bars2 = ax.bar(x, day_min, width, bottom=night_min, label='Дневной сон', color='#2ecc71')

    ax.set_xlabel('Дата')
    ax.set_ylabel('Время сна')
    title = 'Сон за последние 7 дней (МСК)'
    if child_name:
        title = f'Сон за последние 7 дней для {child_name} (МСК)'
    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(dates)
    ax.legend()
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    ax.set_ylim(bottom=0)

    # Format Y-axis labels to HH:MM
    ax.yaxis.set_major_formatter(FuncFormatter(format_minutes_to_hhmm))

    for i in x:
        total_min = night_min[i] + day_min[i]
        if total_min > 0:
            ax.text(i, total_min, format_minutes_to_hhmm(total_min), ha='center', va='bottom')
            if night_min[i] > 0:
                ax.text(i, night_min[i]/2, format_minutes_to_hhmm(night_min[i]), ha='center', va='center', color='white', fontweight='bold')
            if day_min[i] > 0:
                ax.text(i, night_min[i] + day_min[i]/2, format_minutes_to_hhmm(day_min[i]), ha='center', va='center', color='black', fontweight='bold')

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)
    return buf
