import json

from flask import request
from flask_login import current_user

from .models import Vehicle, Expense, DailyChecklist


def _visible_vehicles():
    q = Vehicle.query.filter_by(vehicle_type='MOTORCYCLE')
    if not current_user.is_global_admin:
        q = q.filter_by(base_code=current_user.base_code)
    if not current_user.is_admin:
        q = q.filter_by(driver_id=current_user.id)
    return q.order_by(Vehicle.plate).all()


def _build_metrics(vehicles):
    if not vehicles:
        return {}
    ids = [v.id for v in vehicles]
    metrics = {v.id: {
        'vehicle_id': v.id,
        'plate': v.plate,
        'current_km': int(v.current_km or 0),
        'last_checklist_km': None,
        'previous_checklist_km': None,
        'checklist_delta_km': None,
        'last_fuel_km': None,
        'previous_fuel_km': None,
        'fuel_cycle_km': None,
        'since_fuel_km': None,
        'last_fuel_liters': None,
        'km_per_liter': None,
    } for v in vehicles}

    crows = DailyChecklist.query.filter(
        DailyChecklist.vehicle_id.in_(ids),
        DailyChecklist.is_deleted.is_(False),
    ).with_entities(
        DailyChecklist.vehicle_id,
        DailyChecklist.odometer,
        DailyChecklist.checklist_date,
        DailyChecklist.created_at,
        DailyChecklist.id,
    ).order_by(
        DailyChecklist.vehicle_id,
        DailyChecklist.checklist_date.desc(),
        DailyChecklist.created_at.desc(),
        DailyChecklist.id.desc(),
    ).all()
    seen = {}
    for vid, km, _date, _created, _id in crows:
        if km is None:
            continue
        n = seen.get(vid, 0)
        if n == 0:
            metrics[vid]['last_checklist_km'] = int(km)
        elif n == 1:
            metrics[vid]['previous_checklist_km'] = int(km)
        else:
            continue
        seen[vid] = n + 1
    for vid, m in metrics.items():
        if m['last_checklist_km'] is not None and m['previous_checklist_km'] is not None:
            delta = m['last_checklist_km'] - m['previous_checklist_km']
            # Protege a tela contra um checklist antigo digitado com zeros extras.
            m['checklist_delta_km'] = delta if 0 <= delta <= 1000 else None

    fuels = Expense.query.filter(
        Expense.vehicle_id.in_(ids),
        Expense.expense_type == 'FUEL',
        Expense.asset_type == 'MOTORCYCLE',
        Expense.is_deleted.is_(False),
    ).order_by(
        Expense.vehicle_id,
        Expense.expense_date.desc(),
        Expense.id.desc(),
    ).all()
    seen = {}
    for expense in fuels:
        if expense.odometer is None:
            continue
        vid = expense.vehicle_id
        n = seen.get(vid, 0)
        if n == 0:
            metrics[vid]['last_fuel_km'] = int(expense.odometer)
            if expense.fuel and expense.fuel.liters is not None:
                try:
                    metrics[vid]['last_fuel_liters'] = float(expense.fuel.liters)
                except Exception:
                    pass
        elif n == 1:
            metrics[vid]['previous_fuel_km'] = int(expense.odometer)
        else:
            continue
        seen[vid] = n + 1

    for vid, m in metrics.items():
        current_reference = m['last_checklist_km'] if m['last_checklist_km'] is not None else m['current_km']
        if m['last_fuel_km'] is not None:
            delta = current_reference - m['last_fuel_km']
            m['since_fuel_km'] = delta if 0 <= delta <= 1500 else None
        if m['last_fuel_km'] is not None and m['previous_fuel_km'] is not None:
            cycle = m['last_fuel_km'] - m['previous_fuel_km']
            if 0 <= cycle <= 1500:
                m['fuel_cycle_km'] = cycle
                liters = m['last_fuel_liters']
                if liters and liters > 0:
                    m['km_per_liter'] = round(cycle / liters, 1)
    return metrics


def _inject_ui(html, metrics):
    payload = json.dumps(metrics, ensure_ascii=False)
    css = '''<style id="vehicleMetricsStyle">
    .bike-km-metrics{display:grid;grid-template-columns:1fr 1fr;gap:5px 10px;margin-top:9px;padding-top:8px;border-top:1px solid rgba(255,255,255,.08)}
    .bike-km-metrics span{font-size:8px;color:#8da5b7}.bike-km-metrics b{color:#5cf0e5;font-size:9px}
    .manager-km-line{display:block!important;margin-top:3px!important;color:#7fcfc9!important;font-size:7.5px!important}
    .fuel-metrics-card{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,1fr);gap:7px;padding:9px;border:1px solid #1c4757;border-radius:8px;background:linear-gradient(180deg,#0a202b,#081822)}
    .fuel-metrics-card article{padding:7px;border-radius:7px;background:#08151f;border:1px solid rgba(255,255,255,.055)}.fuel-metrics-card small{display:block;color:#7993a5;font-size:8px}.fuel-metrics-card strong{display:block;color:#4eeee2;font-size:14px;margin-top:3px}.fuel-metrics-card em{display:block;color:#a8bbc8;font-size:7px;font-style:normal;margin-top:2px}
    @media(max-width:760px){.fuel-metrics-card{grid-template-columns:1fr 1fr}.fuel-metrics-card article:last-child{grid-column:1/-1}.bike-km-metrics{grid-template-columns:1fr}}
    </style>'''
    script = f'''<script id="vehicleMetricsScript">(()=>{{
      const metrics={payload}; const list=Object.values(metrics);
      const fmt=v=>v===null||v===undefined?'—':new Intl.NumberFormat('pt-BR').format(v)+' km';
      const plus=v=>v===null||v===undefined?'—':'+'+new Intl.NumberFormat('pt-BR').format(v)+' km';
      const economy=m=>m.km_per_liter!=null?`${{String(m.km_per_liter).replace('.',',')}} km/L`:(m.fuel_cycle_km!=null?`${{new Intl.NumberFormat('pt-BR').format(m.fuel_cycle_km)}} km`:'—');
      const driverCard=document.querySelector('.driver-bike-card');
      if(driverCard&&!driverCard.querySelector('.bike-km-metrics')){{
        const plate=driverCard.querySelector('h2')?.textContent?.trim(); const m=list.find(x=>x.plate===plate);
        if(m){{const d=document.createElement('div');d.className='bike-km-metrics';d.innerHTML=`<span>📍 Último checklist <b>${{plus(m.checklist_delta_km)}}</b></span><span>⛽ Desde abastecimento <b>${{plus(m.since_fuel_km)}}</b></span>${{m.fuel_cycle_km!=null?`<span>📊 Entre abastecimentos <b>${{fmt(m.fuel_cycle_km)}}</b></span>`:''}}${{m.km_per_liter!=null?`<span>⛽ Consumo estimado <b>${{String(m.km_per_liter).replace('.',',')}} km/L</b></span>`:''}}`;driverCard.querySelector('div')?.appendChild(d);}}
      }}
      document.querySelectorAll('.v5-fleet-row').forEach(row=>{{
        const url=row.dataset.historyUrl||row.querySelector('a[href*="/veiculo/"]')?.getAttribute('href')||'';const hit=url.match(/veiculo\/(\d+)/);if(!hit)return;const m=metrics[hit[1]]||metrics[Number(hit[1])];if(!m)return;
        const info=row.querySelector('div:first-child');if(info&&!info.querySelector('.manager-km-line')){{const s=document.createElement('small');s.className='manager-km-line';s.textContent=`📍 checklist ${{plus(m.checklist_delta_km)}} · ⛽ desde abastecimento ${{plus(m.since_fuel_km)}}`;info.appendChild(s);}}
        const fuel=row.querySelector('.v5-fuel');if(fuel){{fuel.textContent='⛽ '+economy(m);fuel.title=m.km_per_liter!=null?'Consumo estimado pelo último ciclo completo de abastecimento':'KM rodados entre os dois últimos abastecimentos';}}
      }});
      const select=document.getElementById('motorcycleVehicle'); const odo=document.getElementById('fuelOdometer');
      if(select&&odo){{
        let card=document.getElementById('fuelMetricsCard');if(!card){{card=document.createElement('div');card.id='fuelMetricsCard';card.className='fuel-metrics-card';const notice=document.querySelector('#receiptForm .notice');(notice||select.closest('label')).insertAdjacentElement('afterend',card);}}
        const update=()=>{{const m=metrics[select.value];if(!m){{card.innerHTML='<article><small>Histórico da moto</small><strong>Selecione a moto</strong></article>';return;}}const informed=parseInt(odo.value||m.current_km||0,10);const live=m.last_fuel_km==null?null:Math.max(0,informed-m.last_fuel_km);card.innerHTML=`<article><small>Desde o último abastecimento</small><strong>${{plus(live)}}</strong><em>Quanto já rodou no tanque atual</em></article><article><small>Último ciclo completo</small><strong>${{fmt(m.fuel_cycle_km)}}</strong><em>Distância entre os 2 últimos abastecimentos</em></article><article><small>Consumo estimado</small><strong>${{m.km_per_liter!=null?String(m.km_per_liter).replace('.',',')+' km/L':'—'}}</strong><em>Calculado quando os litros são informados</em></article>`;}};
        select.addEventListener('change',update);odo.addEventListener('input',update);update();
      }}
    }})();</script>'''
    if 'vehicleMetricsScript' not in html and '</body>' in html:
        html = html.replace('</body>', css + script + '</body>', 1)
    return html


def init_vehicle_metrics_upgrade(app):
    @app.after_request
    def vehicle_metrics_after_request(response):
        if response.mimetype != 'text/html' or not current_user.is_authenticated:
            return response
        if request.endpoint not in {'main.dashboard', 'main.fuel_new'}:
            return response
        try:
            metrics = _build_metrics(_visible_vehicles())
            response.set_data(_inject_ui(response.get_data(as_text=True), metrics))
        except Exception:
            app.logger.exception('Falha ao exibir métricas de KM da frota')
        return response
