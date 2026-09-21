#include <QtWidgets>
#include <QtTest/QTest>
#include <cmath>
#include <functional>
#include <algorithm>

// All scientific content in this standalone prototype is synthetic.
// No production project, catalog or scientific runtime is loaded or modified.
namespace {
const QStringList pages = {"数据管理", "1 智能预测", "2 约束与单因素", "3 综合编图", "验证"};
const QStringList horizons = {"C3", "C6", "D53", "D61", "D62", "D63", "D71", "D72"};
const QVector<QColor> facies = {QColor("#f5995d"), QColor("#f5d760"), QColor("#78c9df"), QColor("#7cbf88"), QColor("#6b97dc")};
QLabel* label(const QString& text, const char* name = nullptr) {
    auto* w = new QLabel(text); if (name) w->setObjectName(name); return w;
}
QWidget* panel(const QString& title, QWidget* content) {
    auto* w = new QFrame; w->setObjectName("panel");
    auto* l = new QVBoxLayout(w); l->setContentsMargins(0,0,0,0); l->setSpacing(0);
    auto* h = label(title, "panelTitle"); h->setMinimumHeight(27); l->addWidget(h); l->addWidget(content,1); return w;
}
QSplitter* split(Qt::Orientation orientation, const QList<QWidget*>& widgets, const QList<int>& sizes) {
    auto* s = new QSplitter(orientation); s->setChildrenCollapsible(false); s->setHandleWidth(5);
    for (auto* w : widgets) s->addWidget(w); s->setSizes(sizes); return s;
}
QTableWidget* table(const QStringList& columns, const QList<QStringList>& rows) {
    auto* t = new QTableWidget(0,columns.size()); t->setHorizontalHeaderLabels(columns);
    t->verticalHeader()->hide(); t->verticalHeader()->setDefaultSectionSize(29);
    t->setAlternatingRowColors(true); t->setSelectionBehavior(QAbstractItemView::SelectRows);
    t->setSelectionMode(QAbstractItemView::SingleSelection); t->setEditTriggers(QAbstractItemView::NoEditTriggers);
    t->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    for (const auto& row : rows) { int r=t->rowCount(); t->insertRow(r); for(int c=0;c<row.size();++c)t->setItem(r,c,new QTableWidgetItem(row[c])); }
    return t;
}

// Numerical demo plots: sampled traces, section interpolation and classifications.
class Plot : public QWidget {
public:
    QString kind, well="A12"; int seed=0, compareMode=0; double cursor=.45;
    std::function<void(double)> clicked;
    explicit Plot(QString k):kind(std::move(k)) {setMinimumSize(120,100); setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Expanding);}
protected:
    void mousePressEvent(QMouseEvent* e) override {cursor=std::clamp((e->position().y()-30)/std::max(1.0,height()-54.0),0.0,1.0);update();if(clicked)clicked(cursor);}
    void paintEvent(QPaintEvent*) override {
        QPainter p(this);p.setRenderHint(QPainter::Antialiasing);p.fillRect(rect(),Qt::white);
        QRectF a(45,30,width()-62,height()-54); if(a.width()<10||a.height()<10)return;
        p.setFont(QFont("Microsoft YaHei UI",8)); p.setPen(QColor("#dce4ec"));
        for(int i=0;i<=5;++i){double y=a.top()+a.height()*i/5.;p.drawLine(QPointF(a.left(),y),QPointF(a.right(),y));p.setPen(QColor("#4b5c6f"));p.drawText(QRectF(0,y-9,40,18),Qt::AlignRight,QString::number(kind=="seismic"?600+i*240:550+i*50));p.setPen(QColor("#dce4ec"));}
        p.setPen(QColor("#728399"));p.drawRect(a);p.drawText(3,16,kind=="seismic"?"时 ms":"深度 m");
        if(kind=="seismic") {
            const int nx=160,ny=100;QImage raster(nx,ny,QImage::Format_RGB32);
            for(int y=0;y<ny;++y)for(int x=0;x<nx;++x){double f=std::sin(y*.61+std::sin(x*.027)*4)+.5*std::sin(y*1.57+x*.035);int v=std::clamp(int(128+f*76),0,255);raster.setPixelColor(x,y,QColor(v,v,v));}
            p.drawImage(a,raster);p.setPen(QPen(QColor("#e36848"),2));QPainterPath line;
            for(int i=0;i<=100;++i){QPointF q(a.left()+a.width()*i/100.,a.top()+a.height()*(.48+.06*std::sin(i*.07)));if(i==0)line.moveTo(q);else line.lineTo(q);}p.drawPath(line);
            p.setPen(QPen(QColor("#0078d4"),1,Qt::DashLine));p.drawLine(QPointF(a.left()+a.width()*.48,a.top()),QPointF(a.left()+a.width()*.48,a.bottom()));
            p.setPen(QColor("#304359"));p.drawText(QRectF(a.left(),4,a.width(),22),Qt::AlignCenter,"L03 · A12定位线 · 合成地震信号");
        } else if(kind=="section") {
            const QStringList wells={"A3","A1","A12","A10","A7"};
            for(int layer=0;layer<5;++layer){QPainterPath s;for(int i=0;i<=80;++i){double x=a.left()+a.width()*i/80.;double y=a.top()+a.height()*(.12+layer*.14+.055*std::sin(i*.08));if(i==0)s.moveTo(x,y);else s.lineTo(x,y);}for(int i=80;i>=0;--i)s.lineTo(a.left()+a.width()*i/80.,a.top()+a.height()*(.26+layer*.14+.055*std::sin(i*.08)));s.closeSubpath();p.fillPath(s,facies[layer]);p.setPen(QPen(QColor("#819ec9"),1));p.drawPath(s);}
            for(int i=0;i<5;++i){double x=a.left()+a.width()*(.08+i*.21);p.fillRect(QRectF(x-5,a.top(),10,a.height()),QColor("#fbf8dd"));p.setPen(QColor("#32465a"));p.drawText(QRectF(x-25,6,50,20),Qt::AlignCenter,wells[i]);QPainterPath trace;for(int j=0;j<=120;++j){double y=a.top()+a.height()*j/120.;double dx=8*std::sin(j*.6+i)+4*std::cos(j*1.7);QPointF q(x-13+dx,y);if(j==0)trace.moveTo(q);else trace.lineTo(q);}p.setPen(QPen(QColor("#31863d"),1));p.drawPath(trace);}
        } else if(kind=="compare") {
            const QStringList titles={"解释相带","预测相带","差异"};
            if(compareMode==0) {
                for(int c=0;c<3;++c){double x=a.left()+a.width()*(c+.2)/3.;double w=a.width()*.22;p.setPen(QColor("#304359"));p.drawText(QRectF(x,4,w,22),Qt::AlignCenter,titles[c]);for(int i=0;i<12;++i){int actual=(i/2+seed)%5;int predicted=(i==4||i==5)?(actual+1)%5:actual;QRectF cell(x,a.top()+a.height()*i/12.,w,a.height()/12.);p.fillRect(cell,c==2?(actual==predicted?QColor("#e4f4e8"):QColor("#fbd5d3")):facies[c==0?actual:predicted]);p.setPen(QColor("#c6d0da"));p.drawRect(cell);}}
            } else {
                p.setPen(QColor("#304359"));p.drawText(QRectF(a.left(),4,a.width(),22),Qt::AlignCenter,compareMode==1?"解释 + 预测叠加（50%）":"差异区间 · 红色不一致 / 绿色一致");
                for(int i=0;i<12;++i){int actual=(i/2+seed)%5,predicted=(i==4||i==5)?(actual+1)%5:actual;QRectF cell(a.left()+a.width()*.15,a.top()+a.height()*i/12.,a.width()*.7,a.height()/12.);if(compareMode==1){p.fillRect(cell,facies[actual]);p.setOpacity(.5);p.fillRect(cell,facies[predicted]);p.setOpacity(1);}else p.fillRect(cell,actual==predicted?QColor("#e4f4e8"):QColor("#f2a7a3"));p.setPen(QColor("#c6d0da"));p.drawRect(cell);}
            }
        } else {
            int count=kind=="single"?1:4;QStringList names={"GR (API)","AC (μs/ft)","DEN (g/cm³)","RT (Ω·m)"};QVector<QColor> colors={QColor("#198947"),QColor("#2478dc"),QColor("#40add0"),QColor("#d95550")};
            for(int c=0;c<count;++c){double left=a.left()+a.width()*c/count;double w=a.width()/count;p.setPen(QColor("#dce4ec"));p.drawLine(QPointF(left,a.top()),QPointF(left,a.bottom()));p.setPen(colors[c]);p.drawText(QRectF(left,4,w,20),Qt::AlignCenter,names[c]);QPainterPath path;for(int i=0;i<200;++i){double v=.5+.2*std::sin(i*.052+seed+c)+.12*std::sin(i*.9+c)+.06*std::cos(i*1.63);QPointF q(left+w*v,a.top()+a.height()*i/199.);if(i==0)path.moveTo(q);else path.lineTo(q);}p.drawPath(path);}
        }
        if(kind!="seismic"){p.setPen(QPen(QColor("#0078d4"),1,Qt::DashLine));double y=a.top()+a.height()*cursor;p.drawLine(QPointF(a.left(),y),QPointF(a.right(),y));}
    }
};

class MapView : public QGraphicsView {
public:
    QGraphicsScene scene;QGraphicsPixmapItem* background=nullptr;QGraphicsItemGroup *wells=nullptr,*lines=nullptr;
    QGraphicsEllipseItem* ring=nullptr;QMap<QString,QPointF> points;std::function<void(QString)> selectWell;QString selected="A12";
    MapView():QGraphicsView() {
        setScene(&scene);
        setRenderHints(QPainter::Antialiasing|QPainter::SmoothPixmapTransform);setBackgroundBrush(Qt::white);setFrameShape(QFrame::NoFrame);
        setDragMode(QGraphicsView::ScrollHandDrag);setTransformationAnchor(AnchorUnderMouse);setMinimumSize(200,120);
        QPixmap asset(":/assets/facies-demo.png");background=scene.addPixmap(asset.scaled(960,600,Qt::KeepAspectRatio,Qt::SmoothTransformation));
        scene.setSceneRect(0,0,960,600);wells=new QGraphicsItemGroup;scene.addItem(wells);
        points={{"A1",{420,335}},{"A2",{415,490}},{"A3",{205,420}},{"A4",{500,433}},{"A5",{330,112}},{"A6",{235,180}},{"A7",{795,421}},{"A8",{495,45}},{"A9",{162,279}},{"A10",{740,230}},{"A11",{456,116}},{"A12",{553,227}},{"A13",{323,400}},{"A14",{675,367}},{"A15",{726,145}},{"A16",{777,283}},{"A17",{713,73}},{"A18",{560,337}},{"A19",{609,514}}};
        for(auto it=points.begin();it!=points.end();++it){auto* dot=new QGraphicsEllipseItem(-4,-4,8,8,wells);dot->setPos(it.value());dot->setBrush(QColor("#f9d35b"));dot->setPen(QPen(Qt::black,1));dot->setData(0,it.key());auto* text=new QGraphicsSimpleTextItem(it.key(),wells);text->setFont(QFont("Segoe UI",10,QFont::Bold));text->setFlag(QGraphicsItem::ItemIgnoresTransformations);text->setBrush(QColor("#182d3d"));text->setPos(it.value()+QPointF(7,-13));text->setData(0,it.key());}
        ring=scene.addEllipse(-10,-10,20,20,QPen(QColor("#0078d4"),3));ring->setZValue(4);ring->setPos(points[selected]);
        lines=new QGraphicsItemGroup;scene.addItem(lines);
        for(int k=0;k<2;++k){QPainterPath path;path.moveTo(260,155+k*85);path.cubicTo(380,210+k*100,620,190+k*80,800,330+k*60);auto* l=new QGraphicsPathItem(path,lines);l->setPen(QPen(k?QColor("#1678db"):QColor("#d65345"),3,Qt::DashLine));}lines->hide();
    }
    void select(const QString& s){if(points.contains(s)){selected=s;ring->setPos(points[s]);}}
    void home(){fitInView(scene.sceneRect(),Qt::KeepAspectRatio);}
protected:
    void resizeEvent(QResizeEvent* e) override {QGraphicsView::resizeEvent(e);home();}
    void wheelEvent(QWheelEvent* e) override {double scaleNow=transform().m11();if((e->angleDelta().y()>0&&scaleNow<5)||(e->angleDelta().y()<0&&scaleNow>.15))scale(e->angleDelta().y()>0?1.15:1/1.15,e->angleDelta().y()>0?1.15:1/1.15);e->accept();}
    void mouseReleaseEvent(QMouseEvent* e) override {auto* item=itemAt(e->pos());if(item&&item->data(0).isValid()){select(item->data(0).toString());if(selectWell)selectWell(selected);}QGraphicsView::mouseReleaseEvent(e);}
};

class Window : public QMainWindow {
public:
    QTabBar* tabs=nullptr;QStackedWidget *content=nullptr,*ribbons=nullptr,*rightPages=nullptr,*assetPreview=nullptr;
    QDockWidget *leftDock=nullptr,*rightDock=nullptr,*logDock=nullptr;
    QTreeWidget* tree=nullptr;QListWidget* workflow=nullptr;QPlainTextEdit* logs=nullptr;
    QLineEdit *search=nullptr,*filter=nullptr;QComboBox *layer=nullptr,*typeFilter=nullptr;
    QStandardItemModel* assets=nullptr;QSortFilterProxyModel* proxy=nullptr;QTableView* assetTable=nullptr;
    QTableWidget* issues=nullptr;QLabel *assetInfo=nullptr,*wellInfo=nullptr,*issueInfo=nullptr,*resultInfo=nullptr,*activity=nullptr;
    QProgressBar* progress=nullptr;QTimer timer;QMap<QString,QAction*> actions;
    QMenu* panelsMenu=nullptr;
    QList<MapView*> maps;QList<Plot*> plots;QList<QTabBar*> horizonBars;QList<QLabel*> mapTitles;
    QList<QToolButton*> ribbonButtons;QString selectedWell="A12",horizon="C6",job;int jobPage=-1;
    bool compact=false,collapsed=false,linked=true;QStringList paths;
    explicit Window(bool restore=true) {
        setWindowTitle("Paleo Workbench — Qt Ribbon 交互原型 · 示例工程");resize(1580,920);setMinimumSize(1000,640);
        auto* root=new QWidget;auto* layout=new QVBoxLayout(root);layout->setContentsMargins(0,0,0,0);layout->setSpacing(0);
        auto* chrome=new QWidget;auto* chromeLayout=new QVBoxLayout(chrome);chromeLayout->setContentsMargins(0,0,0,0);chromeLayout->setSpacing(0);
        auto* nav=new QWidget;auto* nl=new QHBoxLayout(nav);nl->setContentsMargins(8,2,8,2);
        auto* file=new QToolButton;file->setText("文件");file->setPopupMode(QToolButton::InstantPopup);auto* fm=new QMenu(file);
        fm->addAction("打开原型状态…",this,[this]{loadState();});fm->addAction("保存原型状态…",this,[this]{saveStateDialog();});panelsMenu=fm->addMenu("面板");fm->addSeparator();fm->addAction("退出",this,&QWidget::close);file->setMenu(fm);nl->addWidget(file);
        tabs=new QTabBar;tabs->setExpanding(false);tabs->setDrawBase(false);for(const auto& n:pages)tabs->addTab(n);nl->addWidget(tabs);
        nl->addStretch();search=new QLineEdit;search->setPlaceholderText("搜索命令  Ctrl+K");search->setMaximumWidth(190);nl->addWidget(search);
        auto* toggle=new QToolButton;toggle->setText("折叠");toggle->setToolTip("折叠 Ribbon · Ctrl+F1");connect(toggle,&QToolButton::clicked,this,[this]{setCollapsed(!collapsed);});nl->addWidget(toggle);
        auto* density=new QToolButton;density->setText("紧凑");density->setCheckable(true);connect(density,&QToolButton::toggled,this,[this](bool b){setCompact(b);});nl->addWidget(density);
        chromeLayout->addWidget(nav);ribbons=new QStackedWidget;ribbons->setObjectName("ribbon");chromeLayout->addWidget(ribbons);setMenuWidget(chrome);content=new QStackedWidget;layout->addWidget(content,1);setCentralWidget(root);
        createPages();createDocks();createRibbon();
        layer=new QComboBox;layer->addItems(horizons);layer->setCurrentText(horizon);statusBar()->addPermanentWidget(label("当前层位"));statusBar()->addPermanentWidget(layer);
        activity=label("示例数据 · 未连接生产工程");statusBar()->addWidget(activity,1);progress=new QProgressBar;progress->setMaximumWidth(160);progress->hide();statusBar()->addPermanentWidget(progress);
        connect(layer,&QComboBox::currentTextChanged,this,[this](const QString& s){setHorizon(s);});
        connect(tabs,&QTabBar::currentChanged,this,[this](int i){content->setCurrentIndex(i);ribbons->setCurrentIndex(i);rightPages->setCurrentIndex(i);updateWorkflow(i);});
        connect(tabs,&QTabBar::tabBarDoubleClicked,this,[this](int){setCollapsed(!collapsed);});
        auto* fold=new QShortcut(QKeySequence("Ctrl+F1"),this);connect(fold,&QShortcut::activated,this,[this]{setCollapsed(!collapsed);});
        auto* find=new QShortcut(QKeySequence("Ctrl+K"),this);connect(find,&QShortcut::activated,search,qOverload<>(&QWidget::setFocus));
        connect(search,&QLineEdit::returnPressed,this,[this]{QString q=search->text().trimmed();if(q.isEmpty())return;for(auto it=actions.begin();it!=actions.end();++it)if(it.key().contains(q)){it.value()->trigger();return;}activity->setText("没有匹配命令："+q);});
        connect(&timer,&QTimer::timeout,this,[this]{int v=progress->value()+5;progress->setValue(v);if(v>=100){timer.stop();completeJob();}});
        tabs->setCurrentIndex(1);updateWorkflow(1);selectWell("A12");
        if(restore){QSettings s("PaleoWorkbenchPrototype","RibbonQt");restoreGeometry(s.value("geometry").toByteArray());QMainWindow::restoreState(s.value("docks").toByteArray());setCompact(s.value("compact",false).toBool());setCollapsed(s.value("collapsed",false).toBool());}
    }
    void log(const QString& s){logs->appendPlainText(QTime::currentTime().toString("HH:mm:ss")+"  "+s);activity->setText(s);}
    QAction* command(const QString& name,QStyle::StandardPixmap icon=QStyle::SP_FileIcon) {
        if(actions.contains(name))return actions[name];auto* a=new QAction(style()->standardIcon(icon),name,this);actions[name]=a;connect(a,&QAction::triggered,this,[this,name]{execute(name);});return a;
    }
    void setCollapsed(bool b){collapsed=b;ribbons->setVisible(!b);}
    void setCompact(bool b){compact=b;ribbons->setFixedHeight(b?56:94);for(auto* btn:ribbonButtons){btn->setToolButtonStyle(b?Qt::ToolButtonTextBesideIcon:Qt::ToolButtonTextUnderIcon);btn->setIconSize(QSize(b?18:26,b?18:26));btn->setMinimumWidth(b?60:70);}}
    void setHorizon(const QString& h){if(!horizons.contains(h))return;horizon=h;if(layer){QSignalBlocker b(layer);layer->setCurrentText(h);}for(auto* t:horizonBars){QSignalBlocker b(t);t->setCurrentIndex(horizons.indexOf(h));}for(auto* t:mapTitles)t->setText(h+"层"+t->property("suffix").toString());activity->setText("当前层位："+h+" · 示例数据");}
    void selectWell(const QString& w){selectedWell=w;for(auto* m:maps)m->select(w);for(auto* p:plots){p->well=w;p->seed=w.mid(1).toInt();p->update();}if(wellInfo)wellInfo->setText("当前井："+w+"\n层位："+horizon+"\n深度：550–800 m\n来源：原型合成序列\n\n单击地图井点可联动。\n地震定位仅为空间示意，\n不进行 m / ms 直接换算。");}
    void setLinked(bool b){linked=b;for(auto* m:maps)m->selectWell=b?std::function<void(QString)>([this](const QString& s){selectWell(s);}):std::function<void(QString)>();}
    Plot* plot(const QString& kind){auto* p=new Plot(kind);plots<<p;p->clicked=[this,p](double v){if(!linked)return;for(auto* other:plots)if(other!=p&&other->kind!="seismic"&&p->kind!="seismic"){other->cursor=v;other->update();}};return p;}
    QWidget* mapPane(const QString& suffix,bool constraints=false) {
        auto* w=new QWidget;auto* l=new QVBoxLayout(w);l->setContentsMargins(0,0,0,0);l->setSpacing(0);
        auto* ht=new QTabBar;ht->setExpanding(false);for(auto& h:horizons)ht->addTab(h);ht->setCurrentIndex(1);horizonBars<<ht;l->addWidget(ht);
        connect(ht,&QTabBar::currentChanged,this,[this,ht](int i){if(i>=0)setHorizon(ht->tabText(i));});
        auto* title=label(horizon+"层"+suffix,"mapTitle");title->setAlignment(Qt::AlignCenter);title->setProperty("suffix",suffix);mapTitles<<title;l->addWidget(title);
        auto* body=new QWidget;auto* hl=new QHBoxLayout(body);hl->setContentsMargins(0,0,5,0);auto* m=new MapView;maps<<m;m->lines->setVisible(constraints);m->selectWell=[this](const QString& s){selectWell(s);};hl->addWidget(m,1);
        auto* legend=new QWidget;legend->setMaximumWidth(132);auto* ll=new QVBoxLayout(legend);ll->addWidget(label("图例","panelTitle"));QStringList names={"三角洲前缘","三角洲平原","滨浅湖","湖相泥","深湖"};for(int i=0;i<5;++i){auto* row=new QHBoxLayout;auto* swatch=new QFrame;swatch->setFixedSize(16,16);swatch->setStyleSheet("background:"+facies[i].name()+";border:1px solid #778899;");row->addWidget(swatch);row->addWidget(label(names[i]),1);ll->addLayout(row);}ll->addStretch();ll->addWidget(label("比例示意\n0 ——— 20 km\n\n滚轮缩放\n拖动平移\n点井联动"));hl->addWidget(legend);l->addWidget(body,1);return w;
    }
    void createPages() {
        // 0: assets, a real model/proxy/filter selection pipeline.
        auto* dataPage=new QWidget;auto* dl=new QVBoxLayout(dataPage);dl->setContentsMargins(6,6,6,6);
        auto* filters=new QHBoxLayout;filter=new QLineEdit;filter->setPlaceholderText("搜索名称、井号、来源");filters->addWidget(filter,1);typeFilter=new QComboBox;typeFilter->addItems({"所有类型","测井","分层","地震","单因素图","成果"});filters->addWidget(typeFilter);dl->addLayout(filters);
        assets=new QStandardItemModel(0,6,this);assets->setHorizontalHeaderLabels({"名称","类型","所属对象","层位","版本","状态"});
        QList<QStringList> rows={{"A12_GR.las","测井","A12","C6","v3","可用"},{"A12_AC.las","测井","A12","C6","v3","可用"},{"A12_DEN.las","测井","A12","C6","v3","可用"},{"A12_分层.csv","分层","A12","C6","v2","需复核"},{"L03.sgy","地震","project_area","C6","v1","可用"},{"C6_砂体厚度.tif","单因素图","project_area","C6","v4","输入已更新"},{"C6_沉积相图.gpkg","成果","project_area","C6","v5","待验证"}};
        for(const auto& row:rows){QList<QStandardItem*> items;for(const auto& v:row)items<<new QStandardItem(v);assets->appendRow(items);paths<<"示例 / "+row[0];}
        proxy=new QSortFilterProxyModel(this);proxy->setSourceModel(assets);proxy->setFilterKeyColumn(-1);proxy->setFilterCaseSensitivity(Qt::CaseInsensitive);
        assetTable=new QTableView;assetTable->setModel(proxy);assetTable->setSortingEnabled(true);assetTable->setAlternatingRowColors(true);assetTable->setSelectionBehavior(QAbstractItemView::SelectRows);assetTable->setSelectionMode(QAbstractItemView::SingleSelection);assetTable->setEditTriggers(QAbstractItemView::NoEditTriggers);assetTable->verticalHeader()->hide();assetTable->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);assetTable->verticalHeader()->setDefaultSectionSize(30);
        connect(filter,&QLineEdit::textChanged,this,[this](const QString& s){typeFilter->setCurrentIndex(0);proxy->setFilterKeyColumn(-1);proxy->setFilterFixedString(s);});
        connect(typeFilter,&QComboBox::currentIndexChanged,this,[this](int i){QSignalBlocker b(filter);filter->clear();proxy->setFilterKeyColumn(i?1:-1);proxy->setFilterFixedString(i?typeFilter->currentText():"");});
        assetPreview=new QStackedWidget;auto* emptyPreview=label("未解析文件内容。请选择示例测井或地震资产查看合成预览。");emptyPreview->setAlignment(Qt::AlignCenter);emptyPreview->setWordWrap(true);assetPreview->addWidget(emptyPreview);assetPreview->addWidget(panel("测井类型预览 · 合成多曲线，非文件解析结果",plot("logs")));assetPreview->addWidget(panel("地震类型预览 · 合成信号，非文件解析结果",plot("seismic")));
        auto* preview=new QTabWidget;preview->addTab(assetPreview,"数据预览");preview->addTab(table({"版本","来源","说明"},{{"v3","v2","标准化处理 · 示例"},{"v2","v1","深度对齐 · 示例"},{"v1","原始导入","只读"}}),"版本历史");preview->addTab(label("原始测井  →  处理曲线 v3  →  C6预测 v4\n\n选择资产查看元信息；所有数据为原型示例。"),"关联关系");
        dl->addWidget(split(Qt::Vertical,{assetTable,preview},{350,280}),1);content->addWidget(dataPage);
        auto* prediction=split(Qt::Vertical,{mapPane("沉积相智能预测图"),split(Qt::Horizontal,{panel("地震剖面 · L03（合成信号）",plot("seismic")),panel("测井轨道（示例）",plot("logs"))},{1,1})},{440,250});content->addWidget(prediction);
        content->addWidget(split(Qt::Vertical,{mapPane("约束与单因素分析图",true),panel("连井剖面 · A3 — A1 — A12 — A10 — A7",plot("section"))},{430,260}));
        auto* thumbs=new QWidget;auto* tl=new QHBoxLayout(thumbs);tl->setContentsMargins(4,4,4,4);QStringList names={"厚度图","砂地比图","坡度图","最近井距离","预测置信度"};for(int i=0;i<5;++i){auto* b=new QToolButton;b->setText(names[i]+" · 示例");b->setToolButtonStyle(Qt::ToolButtonTextUnderIcon);QImage field(140,72,QImage::Format_RGB32);for(int y=0;y<72;++y)for(int x=0;x<140;++x){double z=.5+.23*std::sin(x*.055+i)+.24*std::cos(y*.075-i);field.setPixelColor(x,y,QColor::fromHsvF(float((1-z)*.65),.65f,.94f));}b->setIcon(QPixmap::fromImage(field));b->setIconSize(QSize(140,72));b->setMinimumHeight(104);b->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Preferred);b->setCheckable(true);if(i==0)b->setChecked(true);tl->addWidget(b);connect(b,&QToolButton::clicked,this,[this,b,thumbs]{for(auto* other:thumbs->findChildren<QToolButton*>())other->setChecked(other==b);log("参考对象："+b->text()+" · 合成标量场，不替换主成果");});}
        content->addWidget(split(Qt::Vertical,{mapPane("沉积相平面图",true),panel("单因素参考 · 合成标量场（交互示例）",thumbs)},{520,130}));
        issues=table({"对象","检查项","状态"},{{"A12","相带不一致","待复核"},{"A13","砂体厚度","通过"},{"C6","输入版本","已过期"},{"地震 L03","层位一致","未执行"}});
        content->addWidget(split(Qt::Vertical,{split(Qt::Horizontal,{mapPane("沉积相图（验证对照）"),panel("地震剖面 · 双程时 ms",plot("seismic"))},{3,2}),panel("井验证 · 沉积相解释 / 沉积相预测（示例）",plot("compare"))},{430,240}));
    }
    QDockWidget* dock(const QString& title,const QString& id,QWidget* widget,Qt::DockWidgetArea area){auto* d=new QDockWidget(title,this);d->setObjectName(id);d->setWidget(widget);d->setMinimumWidth(155);addDockWidget(area,d);return d;}
    void createDocks() {
        logs=new QPlainTextEdit;logs->setReadOnly(true);logDock=dock("任务与日志","logDock",logs,Qt::BottomDockWidgetArea);logDock->hide();
        auto* left=new QWidget;auto* ll=new QVBoxLayout(left);ll->setContentsMargins(3,3,3,3);tree=new QTreeWidget;tree->setHeaderHidden(true);
        auto* project=new QTreeWidgetItem(tree,{"project_area · 示例"});auto* wells=new QTreeWidgetItem(project,{"井数据 (21)"});for(const auto& w:QStringList{"A1","A3","A7","A10","A12","A13","A14","A18","A19"})new QTreeWidgetItem(wells,{w});
        for(const auto& n:QStringList{"地震数据 (1)","层位 / 地层 (9)","解释要素 (12)","约束与单因素图","综合编图","回收站"})new QTreeWidgetItem(project,{n});project->setExpanded(true);wells->setExpanded(true);ll->addWidget(tree,3);ll->addWidget(label("当前工作流","panelTitle"));workflow=new QListWidget;workflow->setMaximumHeight(175);ll->addWidget(workflow,1);leftDock=dock("资源管理器","resourceDock",left,Qt::LeftDockWidgetArea);
        connect(tree,&QTreeWidget::itemClicked,this,[this](QTreeWidgetItem* i,int){if(i->text(0).startsWith('A'))selectWell(i->text(0));});
        connect(workflow,&QListWidget::itemClicked,this,[this](QListWidgetItem* i){execute(i->text());});
        rightPages=new QStackedWidget;assetInfo=label("选择一个资产查看属性");assetInfo->setWordWrap(true);assetInfo->setAlignment(Qt::AlignTop);assetInfo->setMargin(12);rightPages->addWidget(assetInfo);
        for(int i=1;i<=3;++i){auto* rw=new QWidget;auto* rl=new QVBoxLayout(rw);rl->setContentsMargins(8,8,8,8);auto* section=label(i==2?"约束与单因素图层":"图层与显示","panelTitle");rl->addWidget(section);
            for(const auto& s:QStringList{"沉积相 / 单因素底图","井位及井名","物源线与展布线"}){auto* cb=new QCheckBox(s);cb->setChecked(s!="物源线与展布线"||i>1);rl->addWidget(cb);connect(cb,&QCheckBox::toggled,this,[this,i,s](bool b){auto* m=maps[i-1];if(s=="沉积相 / 单因素底图")m->background->setVisible(b);else if(s=="井位及井名"){m->wells->setVisible(b);m->ring->setVisible(b);}else m->lines->setVisible(b);});}
            rl->addWidget(label("底图透明度"));auto* opacity=new QSlider(Qt::Horizontal);opacity->setRange(15,100);opacity->setValue(100);rl->addWidget(opacity);connect(opacity,&QSlider::valueChanged,this,[this,i](int v){maps[i-1]->background->setOpacity(v/100.);});
            auto* params=new QPushButton("参数与样式…");rl->addWidget(params);connect(params,&QPushButton::clicked,this,[this]{parameterDialog();});
            if(i==1){wellInfo=label("");wellInfo->setWordWrap(true);rl->addWidget(wellInfo);}else rl->addWidget(label(i==2?"参考方法：约束 IDW\n单位：m\n\n双击层位标签切换上下文。":"当前成果：v5（示例）\n状态：待验证\n\n参考图只影响显示，\n不改变成果数据。"));rl->addStretch();rightPages->addWidget(rw);
        }
        auto* validation=new QWidget;auto* vl=new QVBoxLayout(validation);vl->setContentsMargins(5,5,5,5);resultInfo=label("示例检查结果 · 尚未运行","panelTitle");resultInfo->setWordWrap(true);vl->addWidget(resultInfo);vl->addWidget(issues,1);issueInfo=label("请选择问题");issueInfo->setWordWrap(true);vl->addWidget(issueInfo);auto* notes=new QPlainTextEdit;notes->setPlaceholderText("复核备注（必须填写）");notes->setMaximumHeight(90);vl->addWidget(notes);auto* review=new QPushButton("记录人工复核");vl->addWidget(review);connect(review,&QPushButton::clicked,this,[this,notes]{int row=issues->currentRow();if(row<0||notes->toPlainText().trimmed().isEmpty()){log("请选择问题并填写复核备注");return;}issues->item(row,2)->setText("已复核 · 原结论保留");issues->item(row,2)->setData(Qt::UserRole,notes->toPlainText());log("已记录人工复核；原检查结论未改为通过");});rightPages->addWidget(validation);
        rightDock=dock("检查器","inspectorDock",rightPages,Qt::RightDockWidgetArea);resizeDocks({leftDock,rightDock},{220,275},Qt::Horizontal);
        connect(issues,&QTableWidget::currentCellChanged,this,[this](int r,int,int,int){if(r<0)return;const auto w=issues->item(r,0)->text();if(w.startsWith('A'))selectWell(w);issueInfo->setText("对象："+w+"\n检查："+issues->item(r,1)->text()+"\n结论："+issues->item(r,2)->text()+"\n证据：原型预设问题，非实际计算\n基准 v3 / 成果 v5");});issues->setCurrentCell(0,0);
        connect(assetTable->selectionModel(),&QItemSelectionModel::currentRowChanged,this,[this](const QModelIndex& index,const QModelIndex&){if(!index.isValid()){assetInfo->setText("没有匹配资产");assetPreview->setCurrentIndex(0);return;}int r=proxy->mapToSource(index).row();QStringList info;for(int c=0;c<6;++c)info<<assets->headerData(c,Qt::Horizontal).toString()+"："+assets->item(r,c)->text();info<<"来源："+paths.value(r)<<""<<"原型只登记文件元信息。\n科学预览均为合成示例。";assetInfo->setText(info.join('\n'));QString type=assets->item(r,1)->text();bool demo=paths.value(r).startsWith("示例 / ");assetPreview->setCurrentIndex(demo?(type=="测井"?1:type=="地震"?2:0):0);QString w=assets->item(r,2)->text();if(w.startsWith('A'))selectWell(w);});assetTable->selectRow(0);
    }
    void updateWorkflow(int i){workflow->clear();QStringList steps;switch(i){case 0:steps={"导入数据","检查数据","版本历史","导出表格"};break;case 1:steps={"检查输入","运行预测","叠加对照","送交验证"};break;case 2:steps={"编辑物源线","计算单因素","连井分析","生成等值线","送交验证"};break;case 3:steps={"相界编辑","参考图","图件整饰","导出图件","送交验证"};break;default:steps={"运行验证","定位问题","记录结论","导出报告"};}workflow->addItems(steps);}
    void createRibbon() {
        using Groups=QList<QPair<QString,QStringList>>;
        QList<Groups> all={
            {{"数据导入",{"导入数据","扫描目录","导入计划"}},{"整理",{"关联到井","设置角色"}},{"质量检查",{"检查数据","单位与坐标"}},{"版本与关联",{"版本历史","来源关系"}},{"输出",{"导出表格"}}},
            {{"输入与模型",{"选择井数据","选择地震","模型参数"}},{"预测运行",{"运行预测","取消","参数"}},{"叠加对照",{"地震叠加","测井叠加","联动"}},{"结果",{"保存结果","送交验证"}}},
            {{"约束编辑",{"编辑物源线","展布线","捕捉"}},{"插值计算",{"计算单因素","参数","取消"}},{"连井分析",{"选井","连井路径","联动"}},{"等值线",{"生成等值线"}},{"结果",{"保存版本","送交验证"}}},
            {{"相界编辑",{"选择","编辑相界"}},{"参考图",{"显示参考图","透明度"}},{"图件整饰",{"标注","图例"}},{"版式",{"模板","纸张","预览"}},{"输出",{"导出图件","保存方案","送交验证"}}},
            {{"对象与基准",{"选择对象","选择基准"}},{"联动对比",{"联动","并排","叠加","差异"}},{"检查",{"运行验证","检查设置","取消"}},{"复核",{"定位问题","记录结论"}},{"报告",{"保存记录","导出报告"}}}
        };
        for(const auto& groups:all){auto* page=new QWidget;auto* row=new QHBoxLayout(page);row->setContentsMargins(6,2,6,2);row->setSpacing(3);
            for(const auto& group:groups){auto* box=new QFrame;box->setObjectName("ribbonGroup");auto* bl=new QVBoxLayout(box);bl->setContentsMargins(4,1,6,0);bl->setSpacing(0);auto* commands=new QHBoxLayout;commands->setSpacing(1);
                for(const auto& n:group.second){auto icon=QStyle::SP_FileDialogDetailedView;if(n.contains("运行")||n.contains("计算")||n.contains("生成"))icon=QStyle::SP_MediaPlay;else if(n.contains("保存"))icon=QStyle::SP_DialogSaveButton;else if(n.contains("导入")||n.contains("选择"))icon=QStyle::SP_DirOpenIcon;else if(n.contains("导出"))icon=QStyle::SP_ArrowRight;else if(n=="取消")icon=QStyle::SP_DialogCancelButton;auto* a=command(n,icon);if(n=="联动"||n=="捕捉"){a->setCheckable(true);a->setChecked(true);}auto* b=new QToolButton;b->setDefaultAction(a);b->setToolTip(n+" · 原型演示");b->setAutoRaise(true);commands->addWidget(b);ribbonButtons<<b;}
                bl->addLayout(commands,1);auto* title=label(group.first,"groupLabel");title->setAlignment(Qt::AlignCenter);bl->addWidget(title);row->addWidget(box);
            }row->addStretch();auto* scroll=new QScrollArea;scroll->setWidget(page);scroll->setWidgetResizable(true);scroll->setFrameShape(QFrame::NoFrame);scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);ribbons->addWidget(scroll);
        }
        setCompact(false);actions["取消"]->setEnabled(false);
        auto* view=panelsMenu;view->addAction(leftDock->toggleViewAction());view->addAction(rightDock->toggleViewAction());view->addAction(logDock->toggleViewAction());view->addAction("恢复布局",this,[this]{leftDock->setFloating(false);rightDock->setFloating(false);addDockWidget(Qt::LeftDockWidgetArea,leftDock);addDockWidget(Qt::RightDockWidgetArea,rightDock);leftDock->show();rightDock->show();resizeDocks({leftDock,rightDock},{220,275},Qt::Horizontal);});
        auto* save=new QShortcut(QKeySequence::Save,this);connect(save,&QShortcut::activated,this,[this]{saveStateDialog();});
    }
    void startJob(const QString& name){if(timer.isActive()){log("已有模拟任务运行，请完成或取消后重试");return;}job=name;jobPage=tabs->currentIndex();progress->setValue(0);progress->show();timer.start(90);actions["取消"]->setEnabled(true);for(const auto& n:{"运行预测","计算单因素","生成等值线","运行验证"})if(actions.contains(n))actions[n]->setEnabled(false);log(name+"：模拟任务已启动（不执行科学计算）");}
    void cancelJob(){if(!timer.isActive())return;timer.stop();progress->hide();setJobActions();log(job+"：已取消，没有生成结果");job.clear();}
    void setJobActions(){actions["取消"]->setEnabled(false);for(const auto& n:{"运行预测","计算单因素","生成等值线","运行验证"})if(actions.contains(n))actions[n]->setEnabled(true);}
    void completeJob(){progress->hide();setJobActions();if(job=="运行验证")resultInfo->setText("示例检查完成 · 1通过 / 2待复核 / 1未执行");log(job+"：演示完成，结果不是科学计算产物");job.clear();}
    void parameterDialog(){QDialog d(this);d.setWindowTitle("原型参数 · 仅用于交互演示");auto* l=new QFormLayout(&d);auto* method=new QComboBox;method->addItems({"约束 IDW","普通 IDW","Kriging"});l->addRow("方法",method);auto* grid=new QSpinBox;grid->setRange(10,2000);grid->setValue(250);grid->setSuffix(" m");l->addRow("网格间距",grid);auto* model=new QComboBox;model->addItems({"相预测 v2 · 示例","井相分类 v1 · 示例"});l->addRow("模型",model);auto* buttons=new QDialogButtonBox(QDialogButtonBox::Ok|QDialogButtonBox::Cancel);l->addRow(buttons);connect(buttons,&QDialogButtonBox::accepted,&d,&QDialog::accept);connect(buttons,&QDialogButtonBox::rejected,&d,&QDialog::reject);if(d.exec()==QDialog::Accepted)log("参数已选择："+method->currentText()+" / "+grid->text()+"（示例）");}
    void execute(const QString& n) {
        if(n=="运行预测"||n=="计算单因素"||n=="生成等值线"||n=="运行验证"){startJob(n);return;}
        if(n=="取消"){cancelJob();return;}if(n=="联动"){setLinked(actions[n]->isChecked());log(linked?"联动已启用":"联动已关闭");return;}
        if(n=="送交验证"){tabs->setCurrentIndex(4);issues->setCurrentCell(0,0);return;}
        if(n=="导入数据"){QStringList files=QFileDialog::getOpenFileNames(this,"登记文件元信息（不解析、不移动文件）");for(const auto& f:files)importFile(f);return;}
        if(n=="扫描目录"){auto dir=QFileDialog::getExistingDirectory(this,"扫描目录（最多登记200个文件）");if(!dir.isEmpty()){const auto files=QDir(dir).entryInfoList(QDir::Files);for(int i=0;i<std::min(200,int(files.size()));++i)importFile(files[i].absoluteFilePath());}return;}
        if(n=="导出报告"||n=="导出表格"){auto f=QFileDialog::getSaveFileName(this,n,QString(),"CSV (*.csv)");if(!f.isEmpty())log(exportCsv(f,n=="导出报告")?"已导出原型CSV":"导出失败");return;}
        if(n=="导出图件"){auto f=QFileDialog::getSaveFileName(this,"导出当前原型视图",QString(),"PNG (*.png)");if(!f.isEmpty())log(content->currentWidget()->grab().save(f)?"已导出原型视图（PNG）":"导出失败");return;}
        if(n.startsWith("保存")){saveStateDialog();return;}
        if(n=="定位问题"){if(issues->currentRow()<0)issues->setCurrentCell(0,0);selectWell(issues->item(issues->currentRow(),0)->text());for(auto* m:maps)m->home();return;}
        if(n=="编辑物源线"||n=="展布线"){maps[1]->lines->show();log(n+"：已显示示例约束线；几何编辑留待生产接线");return;}
        if(n=="显示参考图"){log("参考图带位于主图下方，点击可切换所选参考对象");return;}
        if(n=="并排"||n=="叠加"||n=="差异"){for(auto* p:plots)if(p->kind=="compare"){p->compareMode=n=="并排"?0:n=="叠加"?1:2;p->update();}log("井相带对比模式："+n+" · 合成分类数据");return;}
        if(n=="检查数据"){tabs->setCurrentIndex(0);filter->setText("需复核");log("已筛选需复核的示例资产");return;}
        if(n=="选择井数据"||n=="选择地震"||n=="选择对象"){tabs->setCurrentIndex(0);typeFilter->setCurrentText(n=="选择地震"?"地震":"所有类型");return;}
        if(n=="记录结论"){tabs->setCurrentIndex(4);rightDock->show();log("在右侧填写复核备注，再点击记录人工复核");return;}
        parameterDialog();
    }
    void importFile(const QString& f){QFileInfo info(f);if(!info.isFile())return;QList<QStandardItem*> row;for(const auto& v:QStringList{info.fileName(),"外部文件","未关联",horizon,"—","仅元信息"})row<<new QStandardItem(v);assets->appendRow(row);paths<<info.absoluteFilePath();tabs->setCurrentIndex(0);filter->clear();typeFilter->setCurrentIndex(0);log("已登记 "+info.fileName()+"；文件未移动、未解析");}
    QJsonObject snapshot() const {QJsonArray reviews;for(int r=0;r<issues->rowCount();++r)reviews.append(QJsonObject{{"object",issues->item(r,0)->text()},{"status",issues->item(r,2)->text()},{"note",issues->item(r,2)->data(Qt::UserRole).toString()}});return {{"schema",1},{"prototype",true},{"page",tabs->currentIndex()},{"horizon",horizon},{"well",selectedWell},{"compact",compact},{"collapsed",collapsed},{"reviews",reviews}};}
    bool saveJson(const QString& f){QSaveFile file(f);if(!file.open(QIODevice::WriteOnly))return false;auto bytes=QJsonDocument(snapshot()).toJson();if(file.write(bytes)!=bytes.size()){file.cancelWriting();return false;}return file.commit();}
    bool restoreJson(const QString& f){QFile file(f);if(!file.open(QIODevice::ReadOnly))return false;auto d=QJsonDocument::fromJson(file.readAll());auto o=d.object();if(o["schema"].toInt()!=1||!o["prototype"].toBool())return false;setHorizon(o["horizon"].toString());selectWell(o["well"].toString("A12"));tabs->setCurrentIndex(std::clamp(o["page"].toInt(),0,4));setCompact(o["compact"].toBool());setCollapsed(o["collapsed"].toBool());for(const auto& v:o["reviews"].toArray()){auto r=v.toObject();for(int i=0;i<issues->rowCount();++i)if(issues->item(i,0)->text()==r["object"].toString()){issues->item(i,2)->setText(r["status"].toString());issues->item(i,2)->setData(Qt::UserRole,r["note"].toString());}}return true;}
    void saveStateDialog(){auto f=QFileDialog::getSaveFileName(this,"保存原型状态（不写入真实工程）",QString(),"Prototype (*.json)");if(!f.isEmpty())log(saveJson(f)?"已保存原型状态":"保存失败");}
    void loadState(){auto f=QFileDialog::getOpenFileName(this,"打开原型状态",QString(),"Prototype (*.json)");if(!f.isEmpty())log(restoreJson(f)?"已恢复原型状态":"不是有效的原型状态文件");}
    bool exportCsv(const QString& path,bool report){QString text="原型示例数据，非科学验收结果\r\n";auto quote=[](QString s){s.replace('"',"\"\"");return '"'+s+'"';};if(report){text+="对象,检查项,状态,备注\r\n";for(int r=0;r<issues->rowCount();++r){QStringList row;for(int c=0;c<3;++c)row<<quote(issues->item(r,c)->text());row<<quote(issues->item(r,2)->data(Qt::UserRole).toString());text+=row.join(',')+"\r\n";}}else {text+="名称,类型,所属对象,层位,版本,状态\r\n";for(int r=0;r<proxy->rowCount();++r){QStringList row;for(int c=0;c<6;++c)row<<quote(proxy->index(r,c).data().toString());text+=row.join(',')+"\r\n";}}QSaveFile f(path);if(!f.open(QIODevice::WriteOnly))return false;QByteArray bytes=QByteArray::fromHex("efbbbf")+text.toUtf8();if(f.write(bytes)!=bytes.size()){f.cancelWriting();return false;}return f.commit();}
protected:
    void closeEvent(QCloseEvent* e) override {timer.stop();if(!property("selfTest").toBool()){QSettings s("PaleoWorkbenchPrototype","RibbonQt");s.setValue("geometry",saveGeometry());s.setValue("docks",QMainWindow::saveState());s.setValue("compact",compact);s.setValue("collapsed",collapsed);}QMainWindow::closeEvent(e);}
};

int selfTest(Window& w,const QString& output) {
    QDir().mkpath(output);QTextStream report(stdout);int failures=0;
    auto check=[&](bool ok,const QString& name){report<<(ok?"PASS ":"FAIL ")<<name<<Qt::endl;if(!ok)++failures;};
    w.setProperty("selfTest",true);w.show();QTest::qWait(120);
    check(w.tabs->count()==5,"five native workspaces");
    check(QRawFont::fromFont(qApp->font()).supportsCharacter(QChar(0x4e2d)),"Chinese font available for native and offscreen UI");
    w.tabs->setCurrentIndex(0);w.filter->setText("A12");check(w.proxy->rowCount()==4,"asset filter");w.filter->setText("not-found");check(w.proxy->rowCount()==0,"empty filter");w.filter->clear();
    w.typeFilter->setCurrentText("地震");check(w.proxy->rowCount()==1,"asset type filter");w.assetTable->selectRow(0);check(w.assetPreview->currentIndex()==2,"seismic asset selects seismic preview");w.typeFilter->setCurrentText("测井");w.assetTable->selectRow(0);check(w.assetPreview->currentIndex()==1,"well asset selects synthetic log preview");w.typeFilter->setCurrentText("成果");w.assetTable->selectRow(0);check(w.assetPreview->currentIndex()==0,"unsupported asset does not show unrelated curve");w.typeFilter->setCurrentIndex(0);
    w.selectWell("A13");check(std::all_of(w.maps.begin(),w.maps.end(),[](auto* m){return m->selected=="A13";}),"well selection propagates");
    w.tabs->setCurrentIndex(1);QTest::qWait(80);auto* interactiveMap=w.maps[0];QTest::mouseClick(interactiveMap->viewport(),Qt::LeftButton,Qt::NoModifier,interactiveMap->mapFromScene(interactiveMap->points["A7"]));check(w.selectedWell=="A7","actual map click selects well");
    w.setHorizon("D61");check(std::all_of(w.horizonBars.begin(),w.horizonBars.end(),[](auto* b){return b->tabText(b->currentIndex())=="D61";}),"horizon synchronizes");w.setHorizon("C6");
    w.setCollapsed(true);check(!w.ribbons->isVisible(),"ribbon collapses");w.setCollapsed(false);w.setCompact(true);check(w.ribbons->height()==56,"compact ribbon");w.setCompact(false);
    w.actions["运行预测"]->trigger();QTest::qWait(120);check(w.timer.isActive()&&w.progress->value()>0,"job progress");w.actions["取消"]->trigger();check(!w.timer.isActive()&&w.job.isEmpty(),"job cancellation");
    w.tabs->setCurrentIndex(4);w.actions["运行验证"]->trigger();QTest::qWait(2050);check(!w.timer.isActive()&&w.resultInfo->text().contains("示例检查完成"),"validation completes as explicit simulation");
    w.actions["差异"]->trigger();bool diff=false;for(auto* p:w.plots)if(p->kind=="compare")diff=p->compareMode==2;check(diff,"difference view changes plot mode");w.actions["并排"]->trigger();
    auto* note=w.rightPages->widget(4)->findChild<QPlainTextEdit*>();auto* review=w.rightPages->widget(4)->findChild<QPushButton*>();note->setPlainText("示例复核：保留不一致结论，待补充资料");QTest::mouseClick(review,Qt::LeftButton);check(w.issues->item(0,2)->text().contains("原结论保留")&&!w.issues->item(0,2)->data(Qt::UserRole).toString().isEmpty(),"review records note without converting failure to pass");
    const QString state=output+"/state.json";check(w.saveJson(state),"atomic prototype state save");w.tabs->setCurrentIndex(1);check(w.restoreJson(state)&&w.tabs->currentIndex()==4,"state restore");
    check(w.exportCsv(output+"/validation.csv",true),"validation CSV export");QFile csv(output+"/validation.csv");check(csv.open(QIODevice::ReadOnly)&&csv.readAll().contains(QString("相带不一致").toUtf8()),"export contains actual issue rows");
    w.leftDock->hide();check(!w.leftDock->isVisible(),"dock hide");w.leftDock->show();w.selectWell("A12");
    w.assetTable->selectRow(0);
    for(int i=0;i<5;++i){w.tabs->setCurrentIndex(i);w.resize(1672,941);QTest::qWait(120);check(w.content->currentIndex()==i&&w.rightPages->currentIndex()==i,"page and inspector "+QString::number(i));check(w.grab().save(output+QString("/page-%1.png").arg(i)),"capture page "+QString::number(i));}
    w.resize(1280,720);w.setCompact(true);QTest::qWait(100);check(w.grab().save(output+"/compact-1280.png"),"compact screenshot");
    w.resize(1920,1080);w.setCompact(false);QTest::qWait(100);check(w.grab().save(output+"/wide-1920.png"),"large desktop screenshot");
    report<<"RESULT "<<failures<<" failures"<<Qt::endl;return failures?1:0;
}
}

int main(int argc,char** argv) {
    QApplication app(argc,argv);app.setStyle("Fusion");app.setApplicationName("Paleo Ribbon Prototype");
#ifdef Q_OS_WIN
    // The offscreen plugin does not automatically enumerate Windows fonts.
    // Read system fonts without bundling or copying licensed font files.
    const QString fontDir=qEnvironmentVariable("WINDIR","C:/Windows")+"/Fonts/";
    for(const auto& f:{"msyh.ttc","msyhbd.ttc","segoeui.ttf"})QFontDatabase::addApplicationFont(fontDir+f);
#endif
    app.setFont(QFont("Microsoft YaHei UI",10));
    QPalette palette=app.style()->standardPalette();palette.setColor(QPalette::Button,QColor("#edf2f7"));palette.setColor(QPalette::ButtonText,QColor("#25364a"));palette.setColor(QPalette::PlaceholderText,QColor("#62788e"));palette.setColor(QPalette::Window,QColor("#f1f3f5"));palette.setColor(QPalette::Base,Qt::white);palette.setColor(QPalette::AlternateBase,QColor("#f6f8fa"));palette.setColor(QPalette::Text,QColor("#25364a"));palette.setColor(QPalette::WindowText,QColor("#25364a"));palette.setColor(QPalette::Highlight,QColor("#0078d4"));palette.setColor(QPalette::HighlightedText,Qt::white);app.setPalette(palette);
    app.setStyleSheet("QMainWindow::separator{background:#d1dbe4;width:5px;height:5px;} QDockWidget::title{background:#e9eef3;padding:6px;font-weight:600;} QTabBar::tab{padding:9px 13px;border:0;} QTabBar::tab:selected{color:#0078d4;border-bottom:3px solid #0078d4;background:#f8fbff;} QToolButton{padding:4px;border:1px solid transparent;border-radius:2px;} QToolButton:hover{background:#e1effc;border-color:#bad6ef;} QToolButton:checked{background:#d6eafb;} QFrame#ribbonGroup{border-right:1px solid #ccd7e3;} QLabel#groupLabel{color:#566c82;font-size:11px;} QLabel#panelTitle{padding:4px 8px;background:#eaf0f5;font-weight:600;} QLabel#mapTitle{font-size:18px;font-weight:600;background:white;padding:4px;} QFrame#panel{border:1px solid #d4dee8;} QHeaderView::section{background:#edf2f7;border:0;border-right:1px solid #d4dee8;padding:6px;} QTableView{gridline-color:#e0e6ed;border:1px solid #d4dee8;} QLineEdit,QComboBox,QSpinBox{padding:4px;border:1px solid #c8d5e3;border-radius:2px;} QTreeView{border:0;} QTreeView::item{height:27px;} QListWidget::item{padding:6px;} QPushButton{padding:6px 9px;} QStatusBar{border-top:1px solid #d2dce7;}");
    bool test=app.arguments().contains("--self-test");Window w(!test);if(test){QString out=QDir::currentPath()+"/evidence";int i=app.arguments().indexOf("--output");if(i>=0&&i+1<app.arguments().size())out=app.arguments()[i+1];return selfTest(w,out);}
    w.show();int captureArg=app.arguments().indexOf("--capture");
    if(captureArg>=0&&captureArg+1<app.arguments().size()){
        const QString path=app.arguments()[captureArg+1];
        QTimer::singleShot(1500,&w,[&w,path]{QDir().mkpath(QFileInfo(path).absolutePath());w.grab().save(path);});
    }
    return app.exec();
}
