"use client";

import { useState, useCallback, useRef } from 'react';
import Cropper from 'react-easy-crop';

interface Area {
    x: number;
    y: number;
    width: number;
    height: number;
}

interface LogoCropperProps {
    onCropComplete: (croppedImageBase64: string) => void;
    initialImage?: string;
    className?: string;
}

const createImage = (url: string): Promise<HTMLImageElement> =>
    new Promise((resolve, reject) => {
        const image = new Image();
        image.addEventListener('load', () => resolve(image));
        image.addEventListener('error', (error) => reject(error));
        image.setAttribute('crossOrigin', 'anonymous');
        image.src = url;
    });

const getCroppedImg = async (imageSrc: string, pixelCrop: Area): Promise<string> => {
    const image = await createImage(imageSrc);
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    if (!ctx) {
        throw new Error('Canvas context not available');
    }

    canvas.width = 128;
    canvas.height = 128;

    ctx.drawImage(
        image,
        pixelCrop.x,
        pixelCrop.y,
        pixelCrop.width,
        pixelCrop.height,
        0,
        0,
        128,
        128
    );

    return canvas.toDataURL('image/png');
};

export default function LogoCropper({ onCropComplete, initialImage, className = '' }: LogoCropperProps) {
    const [imageSrc, setImageSrc] = useState<string | null>(initialImage || null);
    const [crop, setCrop] = useState({ x: 0, y: 0 });
    const [zoom, setZoom] = useState(1);
    const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const onCropCompleteHandler = useCallback(
        (croppedArea: Area, croppedAreaPixels: Area) => {
            setCroppedAreaPixels(croppedAreaPixels);
        },
        []
    );

    const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = () => {
                setImageSrc(reader.result as string);
            };
            reader.readAsDataURL(file);
        }
    };

    const handleCrop = async () => {
        if (!imageSrc || !croppedAreaPixels) return;
        const croppedImage = await getCroppedImg(imageSrc, croppedAreaPixels);
        onCropComplete(croppedImage);
    };

    const handleRemoveLogo = () => {
        setImageSrc(null);
        setCrop({ x: 0, y: 0 });
        setZoom(1);
        setCroppedAreaPixels(null);
        onCropComplete('');
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    return (
        <div className={`space-y-6 ${className}`}>
            <div>
                <label className="block text-sm font-medium text-white mb-2">
                    Repository Logo
                </label>
                <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={handleFileSelect}
                    className="block w-full text-sm text-white border-2 border-sleek-details bg-sleek-fill focus:outline-none focus:border-sleek-details focus:ring-1 focus:ring-sleek-details file:mr-4 file:py-2 file:px-4 file:border-0 file:text-sm file:font-semibold file:bg-sleek-details-subtle file:text-white hover:file:bg-sleek-details"
                />
            </div>

            {imageSrc && (
                <div className="space-y-6">
                    <div>
                        <div className="relative h-80 w-full bg-sleek-background border-2 border-sleek-details overflow-hidden">
                            <Cropper
                                image={imageSrc}
                                crop={crop}
                                zoom={zoom}
                                aspect={1}
                                onCropChange={setCrop}
                                onCropComplete={onCropCompleteHandler}
                                onZoomChange={setZoom}
                                cropShape="rect"
                                showGrid={false}
                            />
                        </div>

                        <div className="mt-4 space-y-2">
                            <label className="block text-sm font-medium text-white">
                                Zoom: {Math.round(zoom * 100)}%
                            </label>
                            <input
                                type="range"
                                value={zoom}
                                min={1}
                                max={3}
                                step={0.1}
                                onChange={(e) => setZoom(Number(e.target.value))}
                                className="w-full h-2 bg-sleek-details-subtle appearance-none cursor-pointer"
                                style={{
                                    background: `linear-gradient(to right, #878787 0%, #878787 ${((zoom - 1) / 2) * 100}%, #2D343D ${((zoom - 1) / 2) * 100}%, #2D343D 100%)`
                                }}
                            />
                        </div>
                    </div>

                    <div className="flex justify-center gap-4 pt-4 border-t border-sleek-details">
                        <button
                            onClick={handleCrop}
                            disabled={!croppedAreaPixels}
                            className="px-6 py-2 btn disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Apply Logo
                        </button>
                        <button
                            onClick={handleRemoveLogo}
                            className="px-6 py-2 bg-sleek-details-subtle text-white hover:bg-sleek-details focus:outline-none focus:ring-2 focus:ring-sleek-details focus:ring-offset-2"
                        >
                            Remove Logo
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
} 