package tlv

type Frame struct {
	Type   byte
	Length byte
	Value  []byte
}
