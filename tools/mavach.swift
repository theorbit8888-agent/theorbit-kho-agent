import Foundation
import Vision
import CoreImage
import AppKit
// mavach <ảnh>          : in mã vạch/QR đọc được (mỗi dòng 1 mã)
// mavach <ảnh> --chu    : in thêm các dòng CHỮ đọc được (OCR) với tiền tố "CHU:"
// mavach tao <mã> <png> : tạo mã vạch Code128 để thử
let a = CommandLine.arguments
if a.count > 3 && a[1] == "tao" {
  let f = CIFilter(name: "CICode128BarcodeGenerator")!
  f.setValue(a[2].data(using: .ascii), forKey: "inputMessage")
  let img = f.outputImage!.transformed(by: CGAffineTransform(scaleX: 4, y: 4))
  let rep = NSBitmapImageRep(ciImage: img)
  try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: a[3])); exit(0)
}
let url = URL(fileURLWithPath: a[1])
let bc = VNDetectBarcodesRequest()
var reqs: [VNRequest] = [bc]
let txt = VNRecognizeTextRequest()
txt.recognitionLevel = .accurate
txt.usesLanguageCorrection = false
if a.contains("--chu") { reqs.append(txt) }
try VNImageRequestHandler(url: url).perform(reqs)
for r in bc.results ?? [] { if let s = r.payloadStringValue { print(s) } }
if a.contains("--chu") {
  for r in txt.results ?? [] { if let c = r.topCandidates(1).first { print("CHU:" + c.string) } }
}
