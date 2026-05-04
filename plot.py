import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO

def generate_sleep_chart(sleep_data, child_name=None):
    dates = [d['date'] for d in sleep_data]
    night_hours = [d['night_min'] / 60 for d in sleep_data]
    day_hours = [d['day_min'] / 60 for d in sleep_data]

    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(dates))
    width = 0.5

    bars1 = ax.bar(x, night_hours, width, label='Ночной сон', color='#1f77b4')
    bars2 = ax.bar(x, day_hours, width, bottom=night_hours, label='Дневной сон', color='#ffdd57')

    ax.set_xlabel('Дата')
    ax.set_ylabel('Часы сна')
    title = 'Сон за последние 7 дней (МСК)'
    if child_name:
        title = f'Сон за последние 7 дней для {child_name} (МСК)'
    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(dates)
    ax.legend()
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    ax.set_ylim(bottom=0)

    for i in x:
        total_height = night_hours[i] + day_hours[i]
        if total_height > 0:
            ax.text(i, total_height, f'{total_height:.1f}', ha='center', va='bottom')
            if night_hours[i] > 0:
                ax.text(i, night_hours[i]/2, f'{night_hours[i]:.1f}', ha='center', va='center', color='white', fontweight='bold')
            if day_hours[i] > 0:
                ax.text(i, night_hours[i] + day_hours[i]/2, f'{day_hours[i]:.1f}', ha='center', va='center', color='black', fontweight='bold')

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)
    return buf
