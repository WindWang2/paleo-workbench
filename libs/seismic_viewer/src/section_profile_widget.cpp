#include <pwb/seismic_viewer/section_profile_widget.hpp>
#include <pwb/seismic_viewer/color_maps.hpp>
#include <pwb/seismic_viewer/display_core.hpp>
#include <algorithm>
#include <cmath>
#include <limits>
#include <mutex>
#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFile>
#include <QFileDialog>
#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPushButton>
#include <QSaveFile>
#include <QTextStream>
#include <QVBoxLayout>

namespace pwb::seismic_viewer {
namespace {
class SerializedVolume final : public pwb::viz::ISeismicVolume {
    std::shared_ptr<pwb::viz::ISeismicVolume> source_;
    pwb::viz::VolumeGeometryV1 geometry_;
    std::shared_ptr<const void> lifetime_;
    std::mutex mutex_;
public:
    explicit SerializedVolume(std::shared_ptr<pwb::viz::ISeismicVolume> source)
        : source_(std::move(source)), geometry_(source_->geometry()), lifetime_(source_->lifetime()) {}
    const pwb::viz::VolumeGeometryV1& geometry() const override { return geometry_; }
    std::shared_ptr<const void> lifetime() const override { return lifetime_; }
    std::size_t read_slice(pwb::viz::VolumeAxis axis, std::int64_t index, std::span<float> out) override {
        std::lock_guard lock(mutex_);
        return source_->read_slice(axis, index, out);
    }
};
bool monotone(const std::vector<double>& values) {
    if (values.empty()) return false;
    for (const auto value : values) if (!std::isfinite(value)) return false;
    if (values.size() == 1) return true;
    const bool increasing = values.back() > values.front();
    for (std::size_t k = 1; k < values.size(); ++k)
        if (increasing ? values[k] <= values[k-1] : values[k] >= values[k-1]) return false;
    return true;
}
double fraction(double value, const std::vector<double>& axis) {
    return axis.size() > 1 ? (value-axis.front())/(axis.back()-axis.front()) : 0.5;
}
std::size_t nearest(double value, const std::vector<double>& axis) {
    const auto it = std::lower_bound(axis.begin(), axis.end(), value,
        [&](double a, double b) { return axis.back() >= axis.front() ? a < b : a > b; });
    if (it == axis.begin()) return 0;
    if (it == axis.end()) return axis.size()-1;
    const auto k = static_cast<std::size_t>(it-axis.begin());
    return std::abs(axis[k]-value) < std::abs(axis[k-1]-value) ? k : k-1;
}
class ProfileCanvas final : public QWidget {
public:
    std::function<void(QPainter&, QRectF)> paint;
    std::function<void(QPointF, QRectF, bool)> cursor;
    explicit ProfileCanvas(QWidget* parent) : QWidget(parent) { setMouseTracking(true); setMinimumSize(180,150); }
    QRectF plot() const { return QRectF(62, 26, std::max(1,width()-82), std::max(1,height()-72)); }
    void paintEvent(QPaintEvent*) override { QPainter p(this); p.fillRect(rect(), Qt::white); if (paint) paint(p,plot()); }
    void mouseMoveEvent(QMouseEvent* event) override { if(cursor) cursor(event->position(),plot(),false); }
    void mousePressEvent(QMouseEvent* event) override { if(cursor && event->button()==Qt::LeftButton) cursor(event->position(),plot(),true); }
};
}
std::shared_ptr<pwb::viz::ISeismicVolume> serialized_volume(std::shared_ptr<pwb::viz::ISeismicVolume> source) {
    if (!source || std::dynamic_pointer_cast<SerializedVolume>(source)) return source;
    return std::make_shared<SerializedVolume>(std::move(source));
}
struct SectionProfileWidget::Impl {
    SectionProfileData data;
    std::vector<SectionProfileWell> wells;
    QImage image;
    ProfileCanvas* canvas = nullptr;
    QLabel* status = nullptr;
    QComboBox* map = nullptr;
    QDoubleSpinBox* clip = nullptr;
    QCheckBox* reverse = nullptr;
    std::optional<std::pair<double,double>> probe;
    std::function<void(double,double)> on_probe;
    QString diagnostic;
    bool loading = false;
    std::uint64_t generation = 0;
    void rebuild() {
        if (data.amplitude.empty()) return;
        auto values = data.amplitude;
        if (reverse->isChecked()) for(auto& value : values) value = -value;
        const auto range = display::percentile_clip_range(values, clip->value());
        const auto bytes = display::normalize_to_index(values, range.lo, range.hi);
        const auto lut = color_lut(map->currentText().toStdString());
        image = QImage(static_cast<int>(data.distance.size()), static_cast<int>(data.samples.size()), QImage::Format_RGB32);
        for (int t=0;t<image.height();++t) {
            auto* row = reinterpret_cast<QRgb*>(image.scanLine(t));
            for (int x=0;x<image.width();++x) {
                const auto c = lut[bytes[static_cast<std::size_t>(x)*data.samples.size()+t]];
                row[x]=qRgb(c[0],c[1],c[2]);
            }
        }
        canvas->update();
    }
    void paint(QPainter& p, QRectF plot) {
        if (image.isNull()) { p.drawText(plot,Qt::AlignCenter,diagnostic); return; }
        // Coordinate-aware resampling: every output pixel maps through the
        // actual axes, so nonuniform depth/segment spacing is not stretched.
        QImage raster(std::max(1,static_cast<int>(plot.width())),std::max(1,static_cast<int>(plot.height())),QImage::Format_RGB32);
        for(int y=0;y<raster.height();++y) {
            const double z=data.samples.front()+(data.samples.back()-data.samples.front())*(y+0.5)/raster.height();
            const int t=static_cast<int>(nearest(z,data.samples));
            auto* row=reinterpret_cast<QRgb*>(raster.scanLine(y));
            for(int x=0;x<raster.width();++x) {
                const double s=data.distance.front()+(data.distance.back()-data.distance.front())*(x+0.5)/raster.width();
                row[x]=image.pixel(static_cast<int>(nearest(s,data.distance)),t);
            }
        }
        p.drawImage(plot,raster);
        p.setPen(Qt::black); p.drawRect(plot);
        for(int tick=0;tick<=4;++tick) {
            const double f=tick/4.0;
            const double x=plot.left()+f*plot.width(), y=plot.top()+f*plot.height();
            p.drawText(QRectF(x-35,plot.bottom()+5,70,18),Qt::AlignHCenter,QString::number(data.distance.front()+f*(data.distance.back()-data.distance.front()),'g',6));
            p.drawText(QRectF(0,y-9,58,18),Qt::AlignRight,QString::number(data.samples.front()+f*(data.samples.back()-data.samples.front()),'g',6));
        }
        p.drawText(QRectF(plot.left(),plot.bottom()+24,plot.width(),18),Qt::AlignCenter,QString::fromStdString("Distance ("+data.distance_unit+")"));
        p.drawText(QPointF(4,16),QString::fromStdString(data.sample_unit));
        p.save(); p.setClipRect(plot.adjusted(0,-22,0,0));
        for(const auto& well:wells) {
            const double x=plot.left()+fraction(well.distance,data.distance)*plot.width();
            p.setPen(QPen(QColor(20,100,20),2)); p.drawLine(QPointF(x,plot.top()),QPointF(x,plot.bottom()));
            p.drawText(QPointF(x+3,plot.top()-5),QString::fromStdString(well.name));
            for(const auto& top:well.tops) {
                const double y=plot.top()+fraction(top.second,data.samples)*plot.height();
                p.setPen(QPen(Qt::darkMagenta,2)); p.drawLine(QPointF(x-8,y),QPointF(x+8,y));
                p.drawText(QPointF(x+10,y-2),QString::fromStdString(top.first));
            }
            if(well.curve_z.size()==well.curve_values.size() && !well.curve_z.empty()) {
                double lo=std::numeric_limits<double>::infinity(),hi=-lo;
                for(double v:well.curve_values) if(std::isfinite(v)) {lo=std::min(lo,v);hi=std::max(hi,v);}
                QPainterPath path; bool start=true;
                for(std::size_t k=0;k<well.curve_z.size();++k) {
                    if(!std::isfinite(well.curve_values[k]) || !std::isfinite(well.curve_z[k])) {start=true;continue;}
                    const QPointF pt(x+(hi>lo?30*(well.curve_values[k]-lo)/(hi-lo):15),plot.top()+fraction(well.curve_z[k],data.samples)*plot.height());
                    if(start) path.moveTo(pt); else path.lineTo(pt); start=false;
                }
                p.setPen(QPen(Qt::darkGreen,1)); p.drawPath(path);
            }
        }
        if(probe) {
            p.setPen(QPen(Qt::darkCyan,1,Qt::DashLine));
            const double x=plot.left()+fraction(probe->first,data.distance)*plot.width();
            const double y=plot.top()+fraction(probe->second,data.samples)*plot.height();
            p.drawLine(QPointF(x,plot.top()),QPointF(x,plot.bottom())); p.drawLine(QPointF(plot.left(),y),QPointF(plot.right(),y));
        }
        p.restore();
    }
};
SectionProfileWidget::SectionProfileWidget(QWidget* parent):QWidget(parent),impl_(std::make_unique<Impl>()) {
    setObjectName("sectionProfile");
    impl_->canvas=new ProfileCanvas(this); impl_->canvas->setObjectName("sectionProfileCanvas");
    impl_->status=new QLabel(this); impl_->map=new QComboBox(this);
    for(auto name:color_map_names()) impl_->map->addItem(QString::fromUtf8(name.data(),static_cast<int>(name.size())));
    impl_->map->setCurrentText("seismic");
    impl_->clip=new QDoubleSpinBox(this); impl_->clip->setRange(50.0,99.0);impl_->clip->setValue(99);
    impl_->reverse=new QCheckBox(tr("Reverse polarity"),this);
    auto* png=new QPushButton(tr("Export PNG"),this);auto* csv=new QPushButton(tr("Export CSV"),this);
    auto* bar=new QHBoxLayout;bar->addWidget(impl_->map);bar->addWidget(new QLabel(tr("Clip percentile"),this));bar->addWidget(impl_->clip);bar->addWidget(impl_->reverse);bar->addStretch();bar->addWidget(png);bar->addWidget(csv);
    auto* layout=new QVBoxLayout(this);layout->addLayout(bar);layout->addWidget(impl_->canvas,1);layout->addWidget(impl_->status);
    connect(impl_->map,&QComboBox::currentTextChanged,this,[this]{impl_->rebuild();});
    connect(impl_->clip,&QDoubleSpinBox::valueChanged,this,[this]{impl_->rebuild();});
    connect(impl_->reverse,&QCheckBox::toggled,this,[this]{impl_->rebuild();});
    connect(png,&QPushButton::clicked,this,[this]{const auto path=QFileDialog::getSaveFileName(this,tr("Export section"),{},tr("PNG (*.png)"));if(!path.isEmpty()&&!export_png(path)) impl_->status->setText(tr("Export failed"));});
    connect(csv,&QPushButton::clicked,this,[this]{const auto path=QFileDialog::getSaveFileName(this,tr("Export amplitudes and coordinates"),{},tr("CSV (*.csv)"));if(!path.isEmpty()&&!export_csv(path)) impl_->status->setText(tr("Export failed"));});
    impl_->canvas->paint=[this](QPainter& p,QRectF r){impl_->paint(p,r);};
    impl_->canvas->cursor=[this](QPointF point,QRectF plot,bool click){
        if(impl_->image.isNull()||!plot.contains(point)) return;
        const auto& d=impl_->data;
        const double s=d.distance.front()+(d.distance.back()-d.distance.front())*(point.x()-plot.left())/plot.width();
        const double z=d.samples.front()+(d.samples.back()-d.samples.front())*(point.y()-plot.top())/plot.height();
        const float amp=d.amplitude[nearest(s,d.distance)*d.samples.size()+nearest(z,d.samples)];
        impl_->status->setText(QString("s=%1 %2, z=%3 %4, amplitude=%5").arg(s).arg(QString::fromStdString(d.distance_unit)).arg(z).arg(QString::fromStdString(d.sample_unit)).arg(amp));
        if(click){set_probe(s,z);if(impl_->on_probe)impl_->on_probe(s,z);}
    };
    clear(tr("Select a fence or arbitrary line"));
}
SectionProfileWidget::~SectionProfileWidget(){worker_.request_stop();if(worker_.joinable())worker_.join();}
bool SectionProfileWidget::set_data(SectionProfileData data){
    if(!monotone(data.distance)||!monotone(data.samples)||data.distance.size()>static_cast<std::size_t>(std::numeric_limits<int>::max())||data.samples.size()>static_cast<std::size_t>(std::numeric_limits<int>::max())||data.amplitude.size()/data.distance.size()!=data.samples.size()||data.amplitude.size()!=data.distance.size()*data.samples.size()){
        clear(tr("Invalid section coordinates or amplitude shape"));return false;
    }
    impl_->data=std::move(data);impl_->diagnostic.clear();impl_->status->clear();impl_->probe.reset();impl_->rebuild();return !impl_->image.isNull();
}
void SectionProfileWidget::clear(const QString& message){impl_->data={};impl_->image={};impl_->wells.clear();impl_->probe.reset();impl_->diagnostic=message;impl_->status->setText(message);impl_->canvas->update();}
void SectionProfileWidget::set_wells(std::vector<SectionProfileWell> wells){impl_->wells=std::move(wells);impl_->canvas->update();}
void SectionProfileWidget::set_probe(double distance,double sample){impl_->probe={{distance,sample}};impl_->canvas->update();}
void SectionProfileWidget::set_probe_callback(std::function<void(double,double)> callback){impl_->on_probe=std::move(callback);}
void SectionProfileWidget::set_color_map(const std::string& name){if(!color_lut(name).empty())impl_->map->setCurrentText(QString::fromStdString(name));}
const SectionProfileData& SectionProfileWidget::data()const{return impl_->data;}
const QImage& SectionProfileWidget::image()const{return impl_->image;}
QString SectionProfileWidget::diagnostic()const{return impl_->diagnostic;}
bool SectionProfileWidget::loading()const{return impl_->loading;}
bool SectionProfileWidget::export_csv(const QString& path)const{
    if(impl_->image.isNull())return false;QSaveFile file(path);if(!file.open(QIODevice::WriteOnly|QIODevice::Text))return false;
    QTextStream out(&file);out.setRealNumberPrecision(17);out<<"distance,sample,amplitude\n";
    const auto& d=impl_->data;for(std::size_t x=0;x<d.distance.size();++x)for(std::size_t t=0;t<d.samples.size();++t)out<<d.distance[x]<<','<<d.samples[t]<<','<<d.amplitude[x*d.samples.size()+t]<<'\n';
    out.flush();return out.status()==QTextStream::Ok&&file.commit();
}
bool SectionProfileWidget::export_png(const QString& path){return !impl_->image.isNull()&&impl_->canvas->grab().save(path,"PNG");}
void SectionProfileWidget::load_polyline(std::shared_ptr<pwb::viz::ISeismicVolume> source,std::vector<std::pair<double,double>> vertices){
    worker_.request_stop();if(worker_.joinable())worker_.join();const auto generation=++impl_->generation;
    clear(tr("Loading arbitrary section..."));impl_->loading=true;
    worker_=std::jthread([this,source=std::move(source),vertices=std::move(vertices),generation](std::stop_token stop){
        SectionProfileData data;QString error;
        try{
            if(!source||vertices.size()<2)throw std::invalid_argument("at least two vertices and a volume are required");
            const auto geometry=source->geometry();
            auto result=display::sample_polyline_slice(*source,vertices,1.0,[&]{return stop.stop_requested();});
            data.distance=std::move(result.distances);data.distance_unit="grid units";data.sample_unit=geometry.unit;
            data.samples.resize(static_cast<std::size_t>(result.n_samples));
            for(std::int64_t t=0;t<result.n_samples;++t)data.samples[t]=geometry.origin[2]+t*geometry.step[2];
            data.amplitude.resize(result.section.size());
            for(std::int64_t x=0;x<result.n_points;++x)for(std::int64_t t=0;t<result.n_samples;++t)data.amplitude[x*result.n_samples+t]=result.section[t*result.n_points+x];
        }catch(const std::exception& ex){error=QString::fromUtf8(ex.what());}
        if(stop.stop_requested())return;
        QMetaObject::invokeMethod(this,[this,generation,data=std::move(data),error=std::move(error)]()mutable{
            if(generation!=impl_->generation)return;impl_->loading=false;if(error.isEmpty())set_data(std::move(data));else clear(error);
        },Qt::QueuedConnection);
    });
}
} // namespace pwb::seismic_viewer
