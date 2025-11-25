"""Flask 웹 기반 재고 및 재무 관리 애플리케이션.

기존 inventory_app.py의 DatabaseManager를 재사용하여 웹 인터페이스를 제공합니다.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
from inventory_app import DatabaseManager, ReportGenerator
import datetime as dt
import matplotlib
matplotlib.use('Agg')  # GUI 백엔드 대신 Agg 백엔드 사용
import matplotlib.pyplot as plt
import io
import base64

app = Flask(__name__)
app.secret_key = 'mow_secret_key_2024'

# 기존 데이터베이스 매니저 재사용
db = DatabaseManager()
reporter = ReportGenerator(db)

@app.route('/')
def index():
    """메인 페이지"""
    return render_template('index.html')

@app.route('/inventory')
def inventory():
    """재고 관리 페이지"""
    products = db.fetch_products()
    low_stock = db.get_low_stock()
    return render_template('inventory.html', products=products, low_stock=low_stock)

@app.route('/add_product', methods=['POST'])
def add_product():
    """제품 추가"""
    try:
        db.add_product(
            request.form['product_code'],
            request.form['name'],
            float(request.form['cost']),
            float(request.form['price']),
            int(request.form['stock']),
            int(request.form['reorder_level'])
        )
        flash('제품이 성공적으로 추가되었습니다.', 'success')
    except Exception as e:
        flash(f'오류: {str(e)}', 'error')
    return redirect(url_for('inventory'))

@app.route('/restock', methods=['POST'])
def restock():
    """재고 추가"""
    try:
        db.restock(request.form['product_code'], int(request.form['quantity']))
        flash('재고가 성공적으로 추가되었습니다.', 'success')
    except Exception as e:
        flash(f'오류: {str(e)}', 'error')
    return redirect(url_for('inventory'))

@app.route('/sales')
def sales():
    """판매 관리 페이지"""
    sales_data = db.fetch_sales()
    products = db.fetch_products()
    return render_template('sales.html', sales=sales_data, products=products)

@app.route('/record_sale', methods=['POST'])
def record_sale():
    """판매 기록"""
    try:
        sale = db.record_sale(request.form['product_code'], int(request.form['quantity']))
        flash(f'판매가 기록되었습니다. 수익: ₩{sale["revenue"]:,.0f}', 'success')
    except Exception as e:
        flash(f'오류: {str(e)}', 'error')
    return redirect(url_for('sales'))

@app.route('/reports')
def reports():
    """보고서 페이지"""
    current = dt.date.today()
    return render_template('reports.html', year=current.year, month=current.month)

@app.route('/generate_report', methods=['POST'])
def generate_report():
    """보고서 생성"""
    year = int(request.form['year'])
    month = int(request.form['month'])
    summary = db.get_monthly_summary(year, month)
    return render_template('reports.html', summary=summary, year=year, month=month)

@app.route('/taxes')
def taxes():
    """세금 설정 페이지"""
    rates = db.get_tax_rates()
    return render_template('taxes.html', rates=rates)

@app.route('/update_taxes', methods=['POST'])
def update_taxes():
    """세금율 업데이트"""
    try:
        db.update_tax_rates(float(request.form['vat_rate']), float(request.form['income_tax_rate']))
        flash('세금율이 업데이트되었습니다.', 'success')
    except Exception as e:
        flash(f'오류: {str(e)}', 'error')
    return redirect(url_for('taxes'))

@app.route('/api/products')
def api_products():
    """제품 목록 API"""
    products = db.fetch_products()
    return jsonify(products)

@app.route('/api/sales')
def api_sales():
    """판매 데이터 API"""
    sales = db.fetch_sales()
    return jsonify(sales)

@app.route('/generate_dummy_data')
def generate_dummy_data():
    """더미 데이터 생성"""
    try:
        # 샘플 제품 추가
        sample_products = [
            ("P001", "노트북", 800000, 1200000, 5, 2),
            ("P002", "마우스", 15000, 25000, 20, 5),
            ("P003", "키보드", 30000, 45000, 15, 3),
            ("P004", "모니터", 200000, 280000, 8, 2),
            ("P005", "헤드폰", 50000, 80000, 12, 3),
        ]

        for product in sample_products:
            db.add_product(*product)

        # 샘플 판매 기록 생성 (여러 달에 걸쳐)
        import random
        for month in range(12):  # 최근 12개월
            for week in range(4):  # 매달 4주
                # 각 주에 5-15개의 판매 기록 생성
                num_sales = random.randint(5, 15)
                for _ in range(num_sales):
                    product_codes = ["P001", "P002", "P003", "P004", "P005"]
                    code = random.choice(product_codes)
                    quantity = random.randint(1, 3)

                    # 과거 날짜로 판매 기록 생성
                    sale_date = dt.date.today() - dt.timedelta(days=month*30 + week*7 + random.randint(0, 6))

                    try:
                        # 제품 정보 가져오기
                        product = db.get_product(code)
                        if product and product['stock'] >= quantity:
                            # 직접 데이터베이스에 과거 날짜로 삽입
                            conn = db._connect()
                            cur = conn.cursor()

                            # 재고 차감
                            cur.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                                      (quantity, product['id']))

                            # 판매 기록 (과거 날짜)
                            cur.execute("""
                                INSERT INTO sales(product_id, quantity, sale_price, sale_date)
                                VALUES (?, ?, ?, ?)
                            """, (product['id'], quantity, product['price'], sale_date.isoformat()))

                            # 현금 기록
                            cur.execute("""
                                INSERT INTO cash_movements(description, amount, movement_type, movement_date)
                                VALUES (?, ?, ?, ?)
                            """, (f"{product['name']} 판매 수익", product['price'] * quantity, "IN", sale_date.isoformat()))

                            conn.commit()
                    except Exception as e:
                        pass  # 재고 부족 등은 무시

        flash('더미 데이터가 성공적으로 생성되었습니다!', 'success')
    except Exception as e:
        flash(f'더미 데이터 생성 실패: {str(e)}', 'error')

    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    """그래프 분석 대시보드"""
    chart_url = generate_chart()
    return render_template('dashboard.html', chart_url=chart_url)

def generate_chart():
    """판매 추세 그래프 생성 - 입체적이고 투명한 디자인"""
    try:
        # 최근 12개월 데이터 가져오기
        data = db.get_monthly_trends(12)
        print(f"=== 그래프 생성 디버깅 ===")
        print(f"월별 추세 데이터 개수: {len(data) if data else 0}")

        if data:
            print(f"데이터 샘플: {data[0]}")
            print(f"기간 범위: {data[0]['period']} ~ {data[-1]['period']}")
        else:
            print("데이터가 없습니다.")

        if not data:
            print("데이터가 없어서 그래프를 생성할 수 없습니다.")
            return None

        periods = [row["period"] for row in data]
        revenue = [row["revenue"] for row in data]
        gross_profit = [row["gross_profit"] for row in data]
        vat = [row["vat"] for row in data]
        income_tax = [row["income_tax"] for row in data]

        # 고해상도 그래프 생성
        plt.figure(figsize=(14, 8), dpi=150)

        # 완전 투명 배경 설정
        plt.gcf().set_facecolor((0, 0, 0, 0))  # RGBA 투명
        plt.gca().set_facecolor((0, 0, 0, 0))  # 투명

        # 선 스타일링 - 더 부드럽고 입체적으로
        line_styles = [
            {'color': '#667eea', 'alpha': 0.9, 'linewidth': 4, 'marker': 'o', 'markersize': 9,
             'markerfacecolor': '#667eea', 'markeredgecolor': 'white', 'markeredgewidth': 2,
             'path_effects': None},
            {'color': '#764ba2', 'alpha': 0.9, 'linewidth': 4, 'marker': 's', 'markersize': 9,
             'markerfacecolor': '#764ba2', 'markeredgecolor': 'white', 'markeredgewidth': 2},
            {'color': '#f093fb', 'alpha': 0.8, 'linewidth': 3, 'marker': '^', 'markersize': 8,
             'markerfacecolor': '#f093fb', 'markeredgecolor': 'white', 'markeredgewidth': 1.5},
            {'color': '#f5576c', 'alpha': 0.8, 'linewidth': 3, 'marker': 'v', 'markersize': 8,
             'markerfacecolor': '#f5576c', 'markeredgecolor': 'white', 'markeredgewidth': 1.5}
        ]

        labels = ['매출', '영업이익', '부가가치세', '소득세']
        data_sets = [revenue, gross_profit, vat, income_tax]

        # 각 데이터셋에 대해 부드러운 선 그리기
        for i, (data_set, style, label) in enumerate(zip(data_sets, line_styles, labels)):
            # 메인 선
            plt.plot(periods, data_set, label=label, zorder=3, **style)

            # 데이터 포인트에 glow 효과 (작은 원으로)
            for j, (x, y) in enumerate(zip(periods, data_set)):
                # 외곽 glow
                plt.scatter([x], [y], color=style['color'], alpha=0.2, s=150, zorder=1)
                # 내부 포인트
                plt.scatter([x], [y], color=style['color'], alpha=0.8, s=60, zorder=2)

        # 타이틀과 레이블 스타일링
        plt.title('최근 12개월 매출·이익·세금 추세', fontsize=20, fontweight='bold', pad=30,
                 color='white', alpha=0.9, fontfamily='DejaVu Sans')

        plt.xlabel('기간', fontsize=14, color='white', alpha=0.8, labelpad=15)
        plt.ylabel('금액 (원)', fontsize=14, color='white', alpha=0.8, labelpad=15)

        # 범례 스타일링
        legend = plt.legend(fontsize=12, loc='upper left', frameon=True,
                          facecolor='rgba(255, 255, 255, 0.1)', edgecolor='rgba(255, 255, 255, 0.3)',
                          fancybox=True, shadow=True, borderpad=1)
        for text in legend.get_texts():
            text.set_color('white')
            text.set_alpha(0.9)

        # 그리드 스타일링 - 더 미세하게
        plt.grid(True, alpha=0.2, color='white', linestyle='--', linewidth=0.5)

        # 축 스타일링
        plt.xticks(rotation=45, ha='right', color='white', alpha=0.8, fontsize=11)
        plt.yticks(color='white', alpha=0.8, fontsize=11)

        # 축 선 제거 (깔끔하게)
        plt.gca().spines['top'].set_visible(False)
        plt.gca().spines['right'].set_visible(False)
        plt.gca().spines['left'].set_color('rgba(255, 255, 255, 0.3)')
        plt.gca().spines['bottom'].set_color('rgba(255, 255, 255, 0.3)')

        # 여백 조정
        plt.tight_layout(pad=3.0)

        # 고해상도로 저장
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', transparent=True)
        buf.seek(0)
        chart_data = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close()

        return f'data:image/png;base64,{chart_data}'

    except Exception as e:
        print(f"그래프 생성 오류: {e}")
        return None

if __name__ == '__main__':
    # templates 폴더 생성
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
